"""
Document Analyst Agent
Uses Claude's PDF capabilities to analyze SEC filings and earnings transcripts
"""

import os
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
import requests
from anthropic import Anthropic

# Setup logging
logger = logging.getLogger(__name__)

# Configuration
SEC_FILINGS_DIR = Path("data/sec_filings")
SEC_FILINGS_DIR.mkdir(parents=True, exist_ok=True)

TRANSCRIPTS_DIR = Path("data/transcripts")
TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)

# Cost tracking
DOCUMENT_COST_PER_PAGE = 0.001  # Approximate cost per page
TYPICAL_FILING_PAGES = 50  # Average 10-Q/10-K length
DOCUMENT_ANALYSIS_COST = TYPICAL_FILING_PAGES * DOCUMENT_COST_PER_PAGE  # ~$0.05

# SEC EDGAR API
SEC_BASE_URL = "https://www.sec.gov"
SEC_HEADERS = {
    'User-Agent': 'Trading Bot research@example.com',  # SEC requires user agent
    'Accept-Encoding': 'gzip, deflate'
}

# Initialize Anthropic client
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')
anthropic_client = None

if ANTHROPIC_API_KEY:
    try:
        anthropic_client = Anthropic(api_key=ANTHROPIC_API_KEY)
        logger.info("Anthropic client initialized for document analysis")
    except Exception as e:
        logger.error(f"Failed to initialize Anthropic client: {e}")
else:
    logger.warning("ANTHROPIC_API_KEY not found. Document analysis disabled.")


def fetch_sec_filings(ticker, filing_types=['10-Q', '10-K', '8-K'], limit=3):
    """
    Fetch recent SEC filings for a ticker.
    
    Args:
        ticker: Stock symbol
        filing_types: List of filing types to fetch
        limit: Maximum number of filings per type
        
    Returns:
        dict: {
            'success': bool,
            'filings': [
                {
                    'type': str,
                    'date': str,
                    'url': str,
                    'local_path': str or None
                }
            ],
            'error': str or None
        }
    """
    try:
        logger.info(f"{ticker}: Fetching SEC filings...")
        
        # Get CIK (Central Index Key) for ticker
        cik = get_cik_for_ticker(ticker)
        if not cik:
            logger.error(f"{ticker}: Could not find CIK")
            return {
                'success': False,
                'filings': [],
                'error': 'Could not find CIK for ticker'
            }
        
        logger.info(f"{ticker}: CIK = {cik}")
        
        # Fetch company filings
        filings_url = f"{SEC_BASE_URL}/cgi-bin/browse-edgar"
        params = {
            'action': 'getcompany',
            'CIK': cik,
            'type': '',
            'dateb': '',
            'owner': 'exclude',
            'count': 100,
            'output': 'atom'
        }
        
        response = requests.get(filings_url, params=params, headers=SEC_HEADERS, timeout=30)
        response.raise_for_status()
        
        # Parse filings (simplified - would need proper XML parsing)
        filings = []
        
        # For now, return structure without actual downloads
        # In production, would parse XML and download PDFs
        logger.info(f"{ticker}: SEC filings fetched (parsing not fully implemented)")
        
        return {
            'success': True,
            'filings': filings,
            'error': None,
            'note': 'Full SEC filing download not yet implemented - placeholder for structure'
        }
        
    except Exception as e:
        logger.error(f"{ticker}: Error fetching SEC filings: {type(e).__name__}: {str(e)}")
        return {
            'success': False,
            'filings': [],
            'error': f"{type(e).__name__}: {str(e)}"
        }


def get_cik_for_ticker(ticker):
    """
    Get SEC CIK (Central Index Key) for a ticker symbol.
    
    Args:
        ticker: Stock symbol
        
    Returns:
        str: CIK number or None
    """
    try:
        # Use SEC company tickers JSON
        tickers_url = "https://www.sec.gov/files/company_tickers.json"
        response = requests.get(tickers_url, headers=SEC_HEADERS, timeout=30)
        response.raise_for_status()
        
        data = response.json()
        
        # Search for ticker
        for entry in data.values():
            if entry.get('ticker', '').upper() == ticker.upper():
                cik = str(entry['cik_str']).zfill(10)  # Pad to 10 digits
                return cik
        
        return None
        
    except Exception as e:
        logger.error(f"Error getting CIK for {ticker}: {type(e).__name__}: {str(e)}")
        return None


def analyze_filing_with_claude(ticker, filing_text, filing_type='10-Q'):
    """
    Analyze SEC filing text using Claude.
    
    Note: This uses text input. For PDF support, would need to use
    Claude's PDF document upload feature with base64 encoding.
    
    Args:
        ticker: Stock symbol
        filing_text: Text content of filing
        filing_type: Type of filing (10-Q, 10-K, 8-K)
        
    Returns:
        dict: {
            'success': bool,
            'risk_score': int (0-100),
            'financial_health': str,
            'key_findings': list,
            'revenue_trend': str,
            'debt_concerns': str,
            'management_warnings': list,
            'hidden_risks': list,
            'summary': str,
            'cost': float,
            'error': str or None
        }
    """
    if not anthropic_client:
        logger.error(f"{ticker}: Anthropic client not initialized")
        return {
            'success': False,
            'risk_score': None,
            'error': 'Anthropic client not initialized'
        }
    
    try:
        logger.info(f"{ticker}: Analyzing {filing_type} filing with Claude...")
        
        # Truncate filing if too long (Claude has token limits)
        max_chars = 100000  # ~25k tokens
        if len(filing_text) > max_chars:
            logger.warning(f"{ticker}: Filing text truncated from {len(filing_text)} to {max_chars} chars")
            filing_text = filing_text[:max_chars] + "\n\n[TRUNCATED]"
        
        # Create analysis prompt
        prompt = f"""Analyze this SEC {filing_type} filing for {ticker} and provide a comprehensive risk assessment.

Focus on:

1. **Revenue Trends**: 
   - Is revenue growing, declining, or flat?
   - Any concerning trends or seasonality issues?
   - Quality of revenue (recurring vs one-time)?

2. **Debt and Liquidity Concerns**:
   - Debt levels and debt-to-equity ratio
   - Cash position and burn rate
   - Ability to service debt
   - Covenant violations or risks

3. **Management Warnings and Disclosures**:
   - Risk factors highlighted by management
   - Going concern warnings
   - Legal or regulatory issues
   - Changes in accounting methods

4. **Hidden Risks**:
   - Off-balance sheet liabilities
   - Related party transactions
   - Customer concentration risks
   - Supply chain vulnerabilities
   - Pending litigation

5. **Overall Financial Health**:
   - Profitability trends
   - Operating margins
   - Cash flow quality
   - Working capital position

Return your analysis as a JSON object:
{{
    "risk_score": 0-100 (0=very safe, 100=very risky),
    "financial_health": "excellent/good/fair/poor/critical",
    "revenue_trend": "strong growth/moderate growth/flat/declining/concerning",
    "debt_concerns": "none/minor/moderate/significant/severe",
    "key_findings": [
        "finding 1",
        "finding 2",
        ...
    ],
    "management_warnings": [
        "warning 1",
        "warning 2",
        ...
    ],
    "hidden_risks": [
        "risk 1",
        "risk 2",
        ...
    ],
    "positive_signals": [
        "signal 1",
        "signal 2",
        ...
    ],
    "red_flags": [
        "flag 1",
        "flag 2",
        ...
    ],
    "summary": "2-3 sentence summary of overall assessment"
}}

SEC Filing Content:
{filing_text}"""
        
        # Call Claude API
        message = anthropic_client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=3000,
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )
        
        # Extract response
        response_text = message.content[0].text
        logger.info(f"{ticker}: Received filing analysis response")
        
        # Parse JSON from response
        try:
            import re
            json_match = re.search(r'```json\s*(.*?)\s*```', response_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
                if json_match:
                    json_str = json_match.group(0)
                else:
                    json_str = response_text
            
            analysis = json.loads(json_str)
            
        except json.JSONDecodeError as e:
            logger.warning(f"{ticker}: Could not parse JSON from response: {e}")
            analysis = {
                'raw_analysis': response_text,
                'parse_error': str(e)
            }
        
        # Calculate cost (estimate based on text length)
        estimated_pages = len(filing_text) / 2000  # ~2000 chars per page
        cost = estimated_pages * DOCUMENT_COST_PER_PAGE
        
        return {
            'success': True,
            'risk_score': analysis.get('risk_score'),
            'financial_health': analysis.get('financial_health'),
            'revenue_trend': analysis.get('revenue_trend'),
            'debt_concerns': analysis.get('debt_concerns'),
            'key_findings': analysis.get('key_findings', []),
            'management_warnings': analysis.get('management_warnings', []),
            'hidden_risks': analysis.get('hidden_risks', []),
            'positive_signals': analysis.get('positive_signals', []),
            'red_flags': analysis.get('red_flags', []),
            'summary': analysis.get('summary'),
            'raw_response': response_text,
            'cost': cost,
            'error': None
        }
        
    except Exception as e:
        logger.error(f"{ticker}: Error analyzing filing: {type(e).__name__}: {str(e)}")
        return {
            'success': False,
            'risk_score': None,
            'error': f"{type(e).__name__}: {str(e)}"
        }


def analyze_earnings_transcript(ticker, transcript_text):
    """
    Analyze earnings call transcript for management tone and sentiment.
    
    Args:
        ticker: Stock symbol
        transcript_text: Earnings call transcript text
        
    Returns:
        dict: {
            'success': bool,
            'sentiment_score': int (0-100, higher=more confident),
            'confidence_level': str,
            'tone_analysis': dict,
            'key_quotes': list,
            'concerns_detected': list,
            'positive_indicators': list,
            'summary': str,
            'cost': float,
            'error': str or None
        }
    """
    if not anthropic_client:
        logger.error(f"{ticker}: Anthropic client not initialized")
        return {
            'success': False,
            'sentiment_score': None,
            'error': 'Anthropic client not initialized'
        }
    
    try:
        logger.info(f"{ticker}: Analyzing earnings transcript with Claude...")
        
        # Truncate if too long
        max_chars = 100000
        if len(transcript_text) > max_chars:
            logger.warning(f"{ticker}: Transcript truncated from {len(transcript_text)} to {max_chars} chars")
            transcript_text = transcript_text[:max_chars] + "\n\n[TRUNCATED]"
        
        # Create analysis prompt
        prompt = f"""Analyze this earnings call transcript for {ticker} and assess management's tone, confidence, and credibility.

Focus on:

1. **Confidence Level**:
   - How confident does management sound about the business?
   - Are they bullish, cautious, or defensive?
   - Do they provide specific guidance or hedge with vague statements?

2. **Tone Analysis**:
   - Optimistic vs pessimistic language
   - Defensive or evasive responses to questions
   - Use of qualifiers ("maybe", "hopefully", "we think")
   - Certainty in forward-looking statements

3. **Red Flags**:
   - Avoiding direct questions
   - Blaming external factors excessively
   - Inconsistencies in messaging
   - Downplaying concerns
   - Vague or non-committal answers

4. **Positive Indicators**:
   - Specific metrics and targets
   - Transparent discussion of challenges
   - Clear strategic vision
   - Confidence in execution
   - Strong Q&A responses

5. **Key Themes**:
   - What are management's main talking points?
   - What concerns are analysts raising?
   - Any surprises or unexpected disclosures?

Return your analysis as a JSON object:
{{
    "sentiment_score": 0-100 (0=very bearish, 50=neutral, 100=very bullish),
    "confidence_level": "very high/high/moderate/low/very low",
    "tone": "optimistic/cautiously optimistic/neutral/cautious/defensive",
    "credibility": "high/medium/low",
    "key_quotes": [
        {{"speaker": "CEO/CFO", "quote": "...", "significance": "..."}},
        ...
    ],
    "concerns_detected": [
        "concern 1",
        "concern 2",
        ...
    ],
    "positive_indicators": [
        "indicator 1",
        "indicator 2",
        ...
    ],
    "red_flags": [
        "flag 1",
        "flag 2",
        ...
    ],
    "analyst_sentiment": "positive/neutral/negative",
    "summary": "2-3 sentence summary of management tone and credibility"
}}

Earnings Call Transcript:
{transcript_text}"""
        
        # Call Claude API
        message = anthropic_client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=3000,
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )
        
        # Extract response
        response_text = message.content[0].text
        logger.info(f"{ticker}: Received transcript analysis response")
        
        # Parse JSON
        try:
            import re
            json_match = re.search(r'```json\s*(.*?)\s*```', response_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
                if json_match:
                    json_str = json_match.group(0)
                else:
                    json_str = response_text
            
            analysis = json.loads(json_str)
            
        except json.JSONDecodeError as e:
            logger.warning(f"{ticker}: Could not parse JSON from response: {e}")
            analysis = {
                'raw_analysis': response_text,
                'parse_error': str(e)
            }
        
        # Calculate cost
        estimated_pages = len(transcript_text) / 2000
        cost = estimated_pages * DOCUMENT_COST_PER_PAGE
        
        return {
            'success': True,
            'sentiment_score': analysis.get('sentiment_score'),
            'confidence_level': analysis.get('confidence_level'),
            'tone': analysis.get('tone'),
            'credibility': analysis.get('credibility'),
            'key_quotes': analysis.get('key_quotes', []),
            'concerns_detected': analysis.get('concerns_detected', []),
            'positive_indicators': analysis.get('positive_indicators', []),
            'red_flags': analysis.get('red_flags', []),
            'analyst_sentiment': analysis.get('analyst_sentiment'),
            'summary': analysis.get('summary'),
            'raw_response': response_text,
            'cost': cost,
            'error': None
        }
        
    except Exception as e:
        logger.error(f"{ticker}: Error analyzing transcript: {type(e).__name__}: {str(e)}")
        return {
            'success': False,
            'sentiment_score': None,
            'error': f"{type(e).__name__}: {str(e)}"
        }


def quick_fundamental_check(ticker, confidence):
    """
    Quick fundamental analysis check for high-confidence candidates.
    
    This is a simplified version that uses available financial data
    without full SEC filing downloads (which require more complex parsing).
    
    Args:
        ticker: Stock symbol
        confidence: Current confidence score
        
    Returns:
        dict: {
            'fundamental_approved': bool,
            'adjusted_confidence': float,
            'risk_score': int or None,
            'analysis': dict or None,
            'cost': float,
            'reason': str
        }
    """
    logger.info(f"{ticker}: Running quick fundamental check (confidence: {confidence:.2f})")
    
    # For now, return a placeholder structure
    # In production, would fetch and analyze actual filings
    
    try:
        # Placeholder: Would fetch recent 10-Q or 10-K
        # For demo, we'll simulate a basic check
        
        logger.info(f"{ticker}: Fundamental analysis not fully implemented - using placeholder")
        
        # Simulate analysis result
        result = {
            'fundamental_approved': True,
            'adjusted_confidence': confidence,
            'risk_score': None,
            'analysis': None,
            'cost': 0,
            'reason': 'Fundamental analysis placeholder - full SEC filing analysis not yet implemented'
        }
        
        return result
        
    except Exception as e:
        logger.error(f"{ticker}: Error in fundamental check: {type(e).__name__}: {str(e)}")
        return {
            'fundamental_approved': False,
            'adjusted_confidence': confidence * 0.9,
            'risk_score': None,
            'analysis': None,
            'cost': 0,
            'reason': f"Fundamental check error: {str(e)}"
        }


def comprehensive_fundamental_analysis(ticker):
    """
    Comprehensive fundamental analysis combining SEC filings and transcripts.
    
    Args:
        ticker: Stock symbol
        
    Returns:
        dict: {
            'success': bool,
            'overall_score': int (0-100),
            'sec_analysis': dict or None,
            'transcript_analysis': dict or None,
            'recommendation': str,
            'total_cost': float,
            'errors': list or None
        }
    """
    logger.info(f"{ticker}: Starting comprehensive fundamental analysis")
    
    total_cost = 0
    errors = []
    
    # Placeholder for full implementation
    logger.info(f"{ticker}: Comprehensive analysis not fully implemented")
    
    return {
        'success': False,
        'overall_score': None,
        'sec_analysis': None,
        'transcript_analysis': None,
        'recommendation': 'Analysis not yet implemented',
        'total_cost': 0,
        'errors': ['Full fundamental analysis not yet implemented']
    }
