# Fortress -> iodhi Service Architecture

## Vision
Fortress recursive intelligence stack exposed as a multi-tenant SaaS service under the iodhi platform via Zenkho LLC.

## Service Tiers

### Tier 1 — Signal Intelligence API
Endpoint: `/api/v1/signal/evaluate`  
Input: symbol, direction, indicators  
Output: critique verdict (CONFIRM/MODIFY/REJECT) + reasoning  
Powered by: `critique_loop.py`  
Pricing: per-call or monthly subscription

### Tier 2 — Sentiment Velocity API
Endpoint: `/api/v1/sentiment/velocity`  
Input: symbol or list of symbols  
Output: velocity score, classification, key themes  
Powered by: `sentiment_velocity_agent.py`

### Tier 3 — Full Intelligence Suite
Includes: screener, critique, sentiment, options flow, cross-asset  
White-labeled for hedge funds, family offices, RIAs  
Pricing: enterprise SaaS

## Multi-Tenancy Requirements
- Each client gets isolated `data/` directory
- LLM costs passed through or absorbed in subscription fee
- Rate limiting per client via `llm_router` rate limiter
- Audit log per client for compliance

## Infrastructure Path
Phase 1: Single-tenant (Fortress for personal trading) <- NOW  
Phase 2: API wrapper around agents (FastAPI) <- Month 3  
Phase 3: Multi-tenant with auth <- Month 6  
Phase 4: iodhi platform dashboard <- Year 1
