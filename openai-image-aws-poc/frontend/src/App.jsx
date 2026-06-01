import { useState } from 'react';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '';

export default function App() {
  const [email, setEmail] = useState('');
  const [prompt, setPrompt] = useState('');
  const [size, setSize] = useState('1024x1024');
  const [quality, setQuality] = useState('medium');
  const [job, setJob] = useState(null);
  const [gallery, setGallery] = useState([]);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState('');

  async function createJob(event) {
    event.preventDefault();
    setLoading(true);
    setMessage('Submitting image job...');
    setJob(null);

    try {
      const response = await fetch(`${API_BASE}/api/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, prompt, size, quality }),
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Request failed');
      }

      const data = await response.json();
      setJob(data);
      setMessage(`Queued successfully. Job ID: ${data.job_id}`);
      pollJob(data.job_id);
    } catch (error) {
      setMessage(error.message);
    } finally {
      setLoading(false);
    }
  }

  async function pollJob(jobId) {
    let finished = false;

    while (!finished) {
      await new Promise((resolve) => setTimeout(resolve, 5000));

      const response = await fetch(`${API_BASE}/api/jobs/${jobId}`);
      const data = await response.json();
      setJob(data);
      setMessage(`Current status: ${data.status}`);

      if (['COMPLETED', 'FAILED'].includes(data.status)) {
        finished = true;
      }
    }
  }

  async function loadGallery() {
    if (!email) {
      setMessage('Enter email first');
      return;
    }

    setMessage('Loading gallery...');
    const response = await fetch(`${API_BASE}/api/users/${encodeURIComponent(email)}/images`);
    const data = await response.json();
    setGallery(data);
    setMessage(`Loaded ${data.length} image jobs`);
  }

  return (
    <main className="page">
      <section className="hero">
        <div>
          <p className="eyebrow">AWS + ECS + SQS + RDS + S3 + OpenAI</p>
          <h1>AI Image Generator</h1>
          <p className="subtext">
            Submit a prompt, process it asynchronously through SQS FIFO, store the result in S3,
            and track every job in PostgreSQL.
          </p>
        </div>
      </section>

      <section className="card">
        <form onSubmit={createJob}>
          <label>Email</label>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="student@example.com"
            required
          />

          <label>Prompt</label>
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="Create a clean 4:3 DevOps architecture diagram showing ECS, SQS, RDS, S3 and OpenAI..."
            required
          />

          <div className="grid">
            <div>
              <label>Size</label>
              <select value={size} onChange={(e) => setSize(e.target.value)}>
                <option value="1024x1024">1024x1024</option>
                <option value="1536x1024">1536x1024</option>
                <option value="1024x1536">1024x1536</option>
                <option value="2048x1152">2048x1152</option>
              </select>
            </div>
            <div>
              <label>Quality</label>
              <select value={quality} onChange={(e) => setQuality(e.target.value)}>
                <option value="low">low</option>
                <option value="medium">medium</option>
                <option value="high">high</option>
                <option value="auto">auto</option>
              </select>
            </div>
          </div>

          <button disabled={loading}>{loading ? 'Submitting...' : 'Generate Image'}</button>
          <button type="button" className="secondary" onClick={loadGallery}>Load My Images</button>
        </form>
      </section>

      {message && <p className="message">{message}</p>}

      {job && (
        <section className="card result">
          <h2>Current Job</h2>
          <p><strong>Job:</strong> {job.job_id}</p>
          <p><strong>Status:</strong> {job.status}</p>
          {job.error && <p className="error"><strong>Error:</strong> {job.error}</p>}
          {job.image_url && <img src={job.image_url} alt="Generated result" />}
        </section>
      )}

      {gallery.length > 0 && (
        <section className="gallery">
          <h2>Your Image Jobs</h2>
          <div className="galleryGrid">
            {gallery.map((item) => (
              <article className="galleryItem" key={item.job_id}>
                {item.image_url ? <img src={item.image_url} alt={item.prompt} /> : <div className="placeholder">{item.status}</div>}
                <p>{item.prompt}</p>
                <small>{item.status}</small>
              </article>
            ))}
          </div>
        </section>
      )}
    </main>
  );
}
