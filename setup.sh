#!/bin/bash
poetry install
echo "OPENAI_API_KEY=your-key-here" > .env
echo ".env" >> .gitignore
echo "✅ Setup complete. Don't forget to replace your OpenAI key in .env!"

