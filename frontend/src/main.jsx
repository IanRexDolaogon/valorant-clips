import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';

const clock = ms => `${Math.floor(ms / 60000)}:${String(Math.floor(ms / 1000) % 60).padStart(2, '0')}`;

async function api(path, options = {}) {
  const token = sessionStorage.getItem('token');
  const headers = { ...(token ? { Authorization: `Bearer ${token}` } : {}), ...options.headers };
  if (options.body && typeof options.body === 'string') headers['Content-Type'] = 'application/json';
  const response = await fetch(`/api${path}`, { ...options, headers });
  if (response.status === 204) return null;
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Check the form values and try again.');
  return data;
}

function App() {
  const [user, setUser] = useState(null), [error, setError] = useState(''), [busy, setBusy] = useState(false);
  const [register, setRegister] = useState(false), [matches, setMatches] = useState([]), [accounts, setAccounts] = useState([]);
  const [recordings, setRecordings] = useState([]), [matchId, setMatchId] = useState(''), [video, setVideo] = useState(null);
  const [file, setFile] = useState(null), [localUrl, setLocalUrl] = useState(''), [kills, setKills] = useState([]);
  const [clips, setClips] = useState([]), [offset, setOffset] = useState('0'), [mode, setMode] = useState('reencode');
  const [progress, setProgress] = useState(0), [media, setMedia] = useState(''), [shared, setShared] = useState('');
  const [folderFiles, setFolderFiles] = useState([]), [expiry, setExpiry] = useState('24');
  const player = useRef(null), mounted = useRef(true);
  const shareToken = window.location.pathname.startsWith('/share/') ? window.location.pathname.split('/')[2] : null;

  async function act(fn) {
    setError(''); setBusy(true);
    try { await fn(); } catch (e) { if (e.name !== 'AbortError') setError(e.message); }
    finally { setBusy(false); }
  }
  async function refresh() {
    const [me, rows, linked, videos] = await Promise.all([api('/auth/me'), api('/matches'), api('/riot/accounts'), api('/videos')]);
    setUser(me); setMatches(rows); setAccounts(linked); setRecordings(videos);
    setMatchId(current => current || String(rows[0]?.id || ''));
  }
  useEffect(() => {
    mounted.current = true;
    if (shareToken) act(async () => setMedia((await api(`/shares/${shareToken}`)).url));
    else if (sessionStorage.getItem('token')) act(refresh);
    return () => { mounted.current = false; };
  }, []);
  useEffect(() => {
    if (!file) { setLocalUrl(''); return; }
    const url = URL.createObjectURL(file); setLocalUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);
  useEffect(() => {
    setKills([]);
    if (user && matchId) api(`/matches/${matchId}/kills`).then(setKills).catch(e => setError(e.message));
  }, [user, matchId]);
  useEffect(() => {
    if (!video) return;
    let cancelled = false, timer;
    const poll = async () => {
      try {
        const rows = await api(`/videos/${video.id}/clips`);
        if (!cancelled) setClips(rows);
        if (!cancelled && rows.some(c => ['queued', 'processing'].includes(c.status))) timer = setTimeout(poll, 2500);
      } catch (e) { if (!cancelled) setError(e.message); }
    };
    poll();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [video]);

  function selectFile(selected) {
    setFile(selected); setVideo(null); setClips([]); setProgress(0); setShared(''); setMedia('');
  }
  async function pickFolder() {
    if (!window.showDirectoryPicker) return;
    const directory = await window.showDirectoryPicker();
    const files = [];
    for await (const handle of directory.values()) {
      if (handle.kind === 'file' && /\.(mp4|mkv|webm)$/i.test(handle.name)) files.push(await handle.getFile());
    }
    setFolderFiles(files);
    if (files.length) selectFile(files[0]);
    else throw new Error('No MP4, MKV or WebM recordings found in this folder.');
  }
  async function upload() {
    if (!file || !matchId) throw new Error('Choose a match and a recording first.');
    if (file.size > 10_000_000) throw new Error('Choose a video no larger than 10 MB.');
    let row = video?.status === 'uploading' ? video : await api('/videos', { method: 'POST', body: JSON.stringify({
      match_id: Number(matchId), original_name: file.name, size_bytes: file.size,
    }) });
    setVideo(row);
    for (let position = row.upload_offset_bytes; position < file.size;) {
      try {
        row = await api(`/videos/${row.id}/chunks?offset=${position}`, { method: 'PUT', body: file.slice(position, position + 8 * 1024 * 1024) });
      } catch (e) {
        // Refresh the committed offset so retrying a lost response never duplicates a chunk.
        row = await api(`/videos/${row.id}`); setVideo(row); throw e;
      }
      position = row.upload_offset_bytes; setVideo(row); setProgress(Math.round(position / file.size * 100));
    }
    row = await api(`/videos/${row.id}/complete`, { method: 'POST' }); setVideo(row);
    setRecordings(await api('/videos'));
  }
  async function plan() {
    await api(`/videos/${video.id}/sync`, { method: 'PATCH', body: JSON.stringify({ sync_offset_ms: Math.round(Number(offset) * 1000) }) });
    await api(`/videos/${video.id}/clips`, { method: 'POST', body: JSON.stringify({ encode_mode: mode }) });
    setVideo({ ...video });
  }
  async function share(clip) {
    const row = await api(`/clips/${clip.id}/shares`, { method: 'POST', body: JSON.stringify({ visibility: 'unlisted',
      expires_at: expiry ? new Date(Date.now() + Number(expiry) * 3600000).toISOString() : null }) });
    setShared(row.url);
  }

  return <div className="shell">
    <header><a className="brand" href="/"><span className="mark">V/</span> VALORANT<span className="muted">CLIPS</span></a>
      <span className="header-note">FROM THE MATCH. FOR THE MOMENT.</span>
      {user && <button className="quiet" onClick={() => { sessionStorage.removeItem('token'); window.location.href = '/'; }}>Sign out</button>}
    </header>
    <main>
      <div className="eyebrow">YOUR HIGHLIGHT REEL STARTS HERE</div>
      <h1>Your best moments.<br /><em>Ready to share.</em></h1>
      <p className="intro">Bring the recording. Keep the kills. Turn your match into clips worth watching again.</p>
      {error && <div className="alert" role="alert">{error}</div>}
      {shareToken ? <section className="panel"><h2>A moment worth sharing</h2>{media && <video src={media} controls autoPlay className="preview" />}
        <button onClick={() => act(async () => setMedia((await api(`/shares/${shareToken}`)).url))} disabled={busy}>Refresh playback link</button></section>
      : !user ? <section className="auth panel"><div><span className="step">01 / GET STARTED</span><h2>{register ? 'Make it yours.' : 'Welcome back.'}</h2>
        <p className="muted">Your recordings stay private until you choose to share a clip.</p></div>
        <form onSubmit={e => { e.preventDefault(); const data = Object.fromEntries(new FormData(e.currentTarget)); act(async () => {
          const result = await api(`/auth/${register ? 'register' : 'login'}`, { method: 'POST', body: JSON.stringify(data) });
          sessionStorage.setItem('token', result.access_token); await refresh();
        }); }}>
          {register && <label>Display name<input name="display_name" maxLength="50" required autoComplete="nickname" /></label>}
          <label>Email<input name="email" type="email" required autoComplete="email" /></label>
          <label>Password<input name="password" type="password" minLength="12" maxLength="128" required autoComplete={register ? 'new-password' : 'current-password'} /></label>
          <button className="primary" disabled={busy}>{busy ? 'One moment…' : register ? 'Create account →' : 'Sign in →'}</button>
          <button className="quiet" type="button" onClick={() => setRegister(!register)}>{register ? 'Already have an account? Sign in' : 'New here? Create an account'}</button>
        </form></section>
      : <>
        <div className="workspace-title"><h2>{user.display_name}’s studio</h2><span className="pill">PRIVATE WORKSPACE</span></div>
        <div className="grid">
          <section className="panel"><span className="step">01 / MATCH</span><h2>Choose your match.</h2>
            <label>Region<select id="region" defaultValue="ap">{['ap','na','eu','kr','br','latam'].map(r => <option key={r}>{r}</option>)}</select></label>
            <button disabled={busy} onClick={() => act(async () => { const result = await api(`/riot/link?region=${document.getElementById('region').value}`); window.location.assign(result.url); })}>Link Riot account ↗</button>
            <p className="hint">Live linking requires Riot approval. A daily developer key alone may not grant VALORANT access.</p>
            <form onSubmit={e => { e.preventDefault(); const data = new FormData(e.currentTarget); act(async () => {
              const result = await api('/matches/import', { method: 'POST', body: JSON.stringify({ account_id: Number(data.get('account_id')), match_id: data.get('match_id') }) });
              await refresh(); setMatchId(String(result.id));
            }); }}>
              <label>Linked account<select name="account_id" required><option value="">Select account</option>{accounts.map(a => <option key={a.id} value={a.id}>{a.game_name}#{a.tag_line}</option>)}</select></label>
              <label>Riot match ID<input name="match_id" required maxLength="100" placeholder="Paste a match ID" /></label>
              <button disabled={busy || !accounts.length}>Import match</button>
            </form>
            <label>Your matches<select value={matchId} onChange={e => { setMatchId(e.target.value); setVideo(null); setClips([]); }}><option value="">Choose a match</option>
              {matches.map(m => <option key={m.id} value={m.id}>{m.queue_id || 'Match'} · {new Date(m.started_at).toLocaleDateString()} · {clock(m.duration_ms)}</option>)}</select></label>
            <p className="hint">{kills.length} kill events available</p>
          </section>
          <section className="panel"><span className="step">02 / RECORDING</span><h2>Bring the footage.</h2>
            <div className="upload-box"><span className="upload-symbol">↥</span><strong>{file?.name || 'Choose your match recording'}</strong><span className="hint">MP4, MKV or WebM · up to 10 MB / 15 seconds · removed after 72 hours</span>
              <label className="file-label">Select a file<input type="file" accept=".mp4,.mkv,.webm" onChange={e => selectFile(e.target.files[0] || null)} /></label>
              {window.showDirectoryPicker && <button className="quiet" disabled={busy} onClick={() => act(pickFolder)}>Or open a recording folder</button>}
            </div>
            {folderFiles.length > 1 && <label>Recording<select onChange={e => selectFile(folderFiles[Number(e.target.value)])}>{folderFiles.map((f,i) => <option value={i} key={i}>{f.name}</option>)}</select></label>}
            {progress > 0 && <><progress max="100" value={progress} aria-label="Upload progress" /><p className="hint">{progress}% uploaded</p></>}
            <button className="primary" disabled={busy || !file || !matchId || video?.status === 'validated'} onClick={() => act(upload)}>{busy ? 'Working…' : video?.status === 'uploading' ? 'Resume upload →' : 'Upload recording →'}</button>
            <label>Uploaded recordings<select value={video?.id || ''} onChange={e => { const row = recordings.find(v => v.id === Number(e.target.value)); setVideo(row || null); setOffset(String((row?.sync_offset_ms || 0) / 1000)); }}>
              <option value="">Select a recording</option>{recordings.filter(v => String(v.match_id) === matchId && v.status === 'validated').map(v => <option key={v.id} value={v.id}>{v.original_name}</option>)}</select></label>
          </section>
        </div>
        <section className="panel sync"><div><span className="step">03 / SYNC & CUT</span><h2>Line up the moment.</h2><p className="muted">Pick a kill, pause the recording at that moment, then align it. The offset is the video time where the match timeline starts.</p>
          <label>Sync offset (seconds)<input type="number" step="0.001" value={offset} onChange={e => setOffset(e.target.value)} /></label>
          <label>Clip method<select value={mode} onChange={e => setMode(e.target.value)}><option value="reencode">Precise cut · re-encode</option><option value="copy">Fast cut · nearest keyframe</option></select></label>
          <div className="kill-list">{kills.slice(0, 50).map(k => <button key={k.id} disabled={!localUrl} onClick={() => { setOffset(String(((player.current?.currentTime || 0) * 1000 - k.time_since_game_start_ms) / 1000)); }}>Align kill at {clock(k.time_since_game_start_ms)}</button>)}</div>
          <button className="primary" disabled={busy || video?.status !== 'validated' || clips.length > 0} onClick={() => act(plan)}>Create my kill clips →</button>
          {clips.length > 0 && <p className="hint">Clips use the saved offset. Use a new recording to change it.</p>}
        </div><div>{localUrl ? <video ref={player} src={localUrl} controls className="preview" /> : <div className="empty-preview">Choose a local recording to preview and align it.<br /><small>Browser playback support varies by recording codec.</small></div>}</div></section>
        <section className="clip-section"><div className="workspace-title"><h2>Your clips <span className="muted">/ {clips.length}</span></h2><span className="pill">{clips.filter(c => c.status === 'ready').length} READY</span></div>
          {!clips.length && <div className="empty-clips">Your next highlight goes here.<span>Upload, sync, and create your first set of clips.</span></div>}
          <div className="clip-grid">{clips.map((clip,i) => <article className="panel clip" key={clip.id}><div className="clip-art"><span>{String(i + 1).padStart(2, '0')}</span><span>{clock(clip.start_ms)} — {clock(clip.end_ms)}</span></div>
            <div className="clip-title"><h3>Kill clip {i + 1}</h3><span className={`status ${clip.status}`}>{clip.status}</span></div>
            <p className="hint">{clip.encode_mode === 'copy' ? 'Fast cut' : 'Precise cut'}{clip.duration_ms != null && ` · processed in ${(clip.duration_ms / 1000).toFixed(2)}s`}</p>
            {clip.error && <p role="alert">{clip.error}</p>}
            <div className="actions"><button disabled={clip.status !== 'ready' || busy} onClick={() => act(async () => setMedia((await api(`/clips/${clip.id}/media`)).url))}>Preview</button><button disabled={clip.status !== 'ready' || busy} onClick={() => act(() => share(clip))}>Share ↗</button></div></article>)}</div>
          <label className="expiry">Share expires after<select value={expiry} onChange={e => setExpiry(e.target.value)}><option value="24">24 hours</option><option value="168">7 days</option><option value="">Never</option></select></label>
          {shared && <div className="share-result"><label>Your share link<input readOnly value={shared} onFocus={e => e.target.select()} /></label><button onClick={() => act(async () => { await navigator.clipboard.writeText(shared); })}>Copy link</button></div>}
          {media && <div className="panel"><video src={media} controls autoPlay className="preview" /><p className="hint">Playback links expire after one minute. Select Preview again to refresh.</p></div>}
        </section>
      </>}
    </main>
    <footer><span>YOUR PLAYS. YOUR FOOTAGE. YOUR MOMENTS.</span><span>Not endorsed by or affiliated with Riot Games.</span></footer>
  </div>;
}

createRoot(document.getElementById('root')).render(<App />);
