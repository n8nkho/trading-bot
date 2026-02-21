#!/usr/bin/env python3
from utils.local_llm import call_ollama

print("Testing Llama 3.2 3B (fast)...")
response = call_ollama("What is RSI? One sentence.", model="llama3.2:3b")
print(f"Response: {response[:100]}\n")

print("Testing Llama 3.1 8B (quality)...")
response = call_ollama("Tesla drops 5% on delivery miss. Fair or unfair?", model="llama3.1:8b")
print(f"Response: {response[:100]}\n")

print("✅ Llama models working!")
print("\nNext: aider --model ollama/llama3.1:8b")
