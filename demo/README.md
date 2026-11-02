# Local demo server (not the real backend)

`server.js` is the original single-file Node prototype. It is kept **only as a local demo**:

- data is in memory and lost on restart
- login is fake and every visitor sees every voice
- spoken consent is not enforced on the server
- it binds to `127.0.0.1` only

```bash
cd demo
npm install
npm start          # http://localhost:5600
```

It serves a frozen copy of the original dashboard from `demo/public/`. Optional: `ELEVENLABS_API_KEY` in `demo/.env.local`, `HF_TOKEN` in the environment.

For the real application (Rust API + Python worker + Whisper consent verification), see the root `README.md`.
