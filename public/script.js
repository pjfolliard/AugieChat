async function loadBranding() {
  const res = await fetch('/branding');
  const data = await res.json();
  document.getElementById('site-name').textContent = data.siteName;
  document.getElementById('logo').src = data.logo;
  document.documentElement.style.setProperty('--primary-color', data.primaryColor);
  document.documentElement.style.setProperty('--secondary-color', data.secondaryColor);
  document.documentElement.style.setProperty('--font-family', data.font);
}

async function sendMessage(message) {
  const res = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message })
  });
  const data = await res.json();
  return data.reply;
}

function addMessage(text, cls) {
  const div = document.createElement('div');
  div.className = `message ${cls}`;
  div.textContent = text;
  document.getElementById('messages').appendChild(div);
}

window.addEventListener('DOMContentLoaded', () => {
  loadBranding();

  const form = document.getElementById('chat-form');
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const input = document.getElementById('message-input');
    const text = input.value;
    addMessage(text, 'user');
    input.value = '';

    const reply = await sendMessage(text);
    addMessage(reply, 'bot');
  });
});
