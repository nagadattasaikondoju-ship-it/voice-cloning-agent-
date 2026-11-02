//! Spoken-consent verification: issue a phrase, transcribe the user's recording with the
//! speech_pipeline (faster-whisper), and compare the transcript to the phrase.

use rand::seq::SliceRandom;

/// Phrases are long and specific so a generic recording cannot pass by accident.
/// Phrases are long and specific so a generic recording cannot pass by accident.
/// Wording avoids words with regional spellings (authorise/authorize) that ASR may vary.
const CONSENT_TEMPLATES: &[&str] = &[
    "I am the owner of this voice and I give Intelligence permission to create a private clone of it for my account. My code words are {code}.",
    "This is my own voice. I agree to let it be cloned for my personal use only. My code words are {code}.",
    "I confirm that I am recording my own voice and I allow a private voice clone to be made from it. My code words are {code}.",
];

/// Common, unambiguous words that speech recognition transcribes reliably.
const CODE_WORDS: &[&str] = &[
    "orange", "river", "window", "garden", "pencil", "rocket", "silver", "yellow", "piano",
    "tiger", "coffee", "planet", "banana", "forest", "mountain", "ocean", "violet", "candle",
];

pub fn generate_phrase() -> String {
    let mut rng = rand::thread_rng();
    let template = CONSENT_TEMPLATES.choose(&mut rng).copied().unwrap_or(CONSENT_TEMPLATES[0]);
    let code: Vec<&str> = CODE_WORDS.choose_multiple(&mut rng, 3).copied().collect();
    template.replace("{code}", &code.join(" "))
}

/// Lowercase, strip punctuation, split into words.
pub fn normalize_words(text: &str) -> Vec<String> {
    text.to_lowercase()
        .chars()
        .map(|c| if c.is_alphanumeric() || c.is_whitespace() || c == '\'' { c } else { ' ' })
        .collect::<String>()
        .replace('\'', "")
        .split_whitespace()
        .map(canonical_word)
        .collect()
}

/// Folds common ASR spelling variants: British -ise/-isation, and "okay"/"ok".
fn canonical_word(w: &str) -> String {
    let w = if w == "ok" { "okay" } else { w };
    for (from, to) in [("isation", "ization"), ("ising", "izing"), ("ised", "ized"), ("ise", "ize")] {
        if w.len() > from.len() + 3 {
            if let Some(stem) = w.strip_suffix(from) {
                return format!("{stem}{to}");
            }
        }
    }
    w.to_string()
}

/// Word-level similarity in [0, 1]: 1 - (word edit distance / phrase length).
/// Tolerates a few misheard words but rejects unrelated speech.
pub fn match_score(expected: &str, transcript: &str) -> f64 {
    let a = normalize_words(expected);
    let b = normalize_words(transcript);
    if a.is_empty() {
        return 0.0;
    }
    let mut prev: Vec<usize> = (0..=b.len()).collect();
    let mut cur = vec![0usize; b.len() + 1];
    for i in 1..=a.len() {
        cur[0] = i;
        for j in 1..=b.len() {
            let cost = if a[i - 1] == b[j - 1] { 0 } else { 1 };
            cur[j] = (prev[j] + 1).min(cur[j - 1] + 1).min(prev[j - 1] + cost);
        }
        std::mem::swap(&mut prev, &mut cur);
    }
    let distance = prev[b.len()] as f64;
    (1.0 - distance / a.len() as f64).max(0.0)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn exact_match_scores_one() {
        let p = "This is my own voice. Code amber river orbit.";
        assert!((match_score(p, "this is my own voice code amber river orbit") - 1.0).abs() < 1e-9);
    }

    #[test]
    fn small_mistakes_still_pass() {
        let p = "I confirm that I am recording my own voice and I allow a private voice clone to be made from it. Code amber river orbit.";
        let t = "I confirm that I'm recording my own voice and I allow a private voice clone to be made from it code amber river orbit";
        assert!(match_score(p, t) >= 0.75, "score {}", match_score(p, t));
    }

    #[test]
    fn british_spelling_is_equivalent() {
        assert!((match_score("I authorize this", "I authorise this") - 1.0).abs() < 1e-9);
    }

    #[test]
    fn truncated_transcript_fails() {
        let p = "I am the owner of this voice and I give Intelligence permission to create a private clone of it for my account. My code words are river piano ocean.";
        assert!(match_score(p, "I am the owner of this voice and I give Intelligence permission") < 0.75);
    }

    #[test]
    fn unrelated_speech_fails() {
        let p = "This is my own voice. I give my consent to clone it for my personal use only. My verification code is amber river orbit.";
        assert!(match_score(p, "hello everyone welcome to my channel today we are talking about cooking") < 0.3);
        assert_eq!(match_score(p, ""), 0.0);
    }

    #[test]
    fn generated_phrase_has_code() {
        let p = generate_phrase();
        assert!(!p.contains("{code}"));
        assert!(normalize_words(&p).len() > 15);
    }
}
