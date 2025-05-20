const express = require('express');
const cors = require('cors');
const { OpenAI } = require('openai');
const path = require('path');
const fs = require('fs');

const app = express();
app.use(cors());
app.use(express.json());

// Load branding configuration
let branding = {
  siteName: 'AugieChat',
  logo: 'logo.png',
  font: 'Arial, sans-serif',
  primaryColor: '#0084ff',
  secondaryColor: '#f5f5f5'
};
try {
  const data = fs.readFileSync(path.join(__dirname, 'branding.json'), 'utf-8');
  branding = { ...branding, ...JSON.parse(data) };
} catch (err) {
  console.log('Using default branding');
}

// Serve static files
app.use(express.static(path.join(__dirname, 'public')));

// OpenAI setup
const openai = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });

app.post('/api/chat', async (req, res) => {
  const { message } = req.body;
  if (!message) {
    return res.status(400).json({ error: 'Message is required' });
  }
  try {
    const completion = await openai.chat.completions.create({
      messages: [{ role: 'user', content: message }],
      model: 'gpt-3.5-turbo'
    });
    const reply = completion.choices[0].message.content.trim();
    res.json({ reply });
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: 'OpenAI API error' });
  }
});

app.get('/branding', (req, res) => {
  res.json(branding);
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log(`Server running on port ${PORT}`));
