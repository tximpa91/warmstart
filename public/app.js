/* Public mode only reads fixtures. The local console explicitly calls the loopback API. */
const local = location.pathname.startsWith('/console/');
const select = id => document.getElementById(id);
const seen = new Set();
let recordings;
if (local) {
  select('mode').textContent = 'Local offline API';
  select('disclosure').textContent = 'This console calls the local Python service with deterministic offline inference. The policies and reviewed-answer candidates are fictional AI-authored drafts. No paid model is called.';
}
select('ask').addEventListener('click', async () => {
  const button = select('ask'); button.disabled = true;
  const question = select('question').value, profile = select('profile').value;
  try {
    let result;
    if (local) {
      const response = await fetch('/v1/answer', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question,profile})});
      if (!response.ok) throw new Error(`Request failed (${response.status}).`);
      result = await response.json();
    } else {
      if (!recordings) recordings = await (await fetch('recordings.json')).json();
      const recording = recordings.find(item => item.profile === profile && item.question === question);
      if (!recording) throw new Error('Recording unavailable.');
      const key = JSON.stringify([profile,question]);
      result = seen.has(key) ? recording.second : recording.first;
      seen.add(key);
    }
    select('answer').textContent = result.answer;
    select('status').textContent = result.cache_status;
    select('version').textContent = result.policy_version;
    select('source').textContent = result.source_ids.join(', ') || 'No policy evidence required';
    select('request').textContent = local ? result.request_id : 'recorded / synthetic';
  } catch (error) {
    select('status').textContent = 'Unavailable'; select('answer').textContent = error.message;
  } finally { button.disabled = false; }
});
