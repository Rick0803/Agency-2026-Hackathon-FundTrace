#!/usr/bin/env python3
"""
Quick test script to verify LLM integration is working.
Run this to check if Bedrock credentials are configured correctly.
"""

import os
import sys

# Add Proto to path
sys.path.insert(0, os.path.dirname(__file__))

from agent.llm_client import call_llm, get_llm_client


def test_llm_client():
    """Test basic LLM client initialization and call."""
    print("Testing LLM client initialization...")
    
    client = get_llm_client()
    if client is None:
        print("❌ LLM client initialization failed - credentials missing or invalid")
        return False
    
    print(f"✓ LLM client initialized successfully: {type(client).__name__}")
    
    # Test a simple call
    print("\nTesting simple LLM call...")
    response = call_llm(
        system_prompt="You are a helpful assistant. Respond in one short sentence.",
        user_prompt="Say hello and confirm you're working.",
        max_tokens=50,
    )
    
    if response:
        print(f"✓ LLM call successful!")
        print(f"Response: {response}")
        return True
    else:
        print("❌ LLM call failed - no response received")
        return False


def test_scan_summary():
    """Test the scan summary generation."""
    print("\n" + "="*60)
    print("Testing scan summary generation...")
    print("="*60)
    
    from views.fetch import _fetch_scan_summary_placeholder
    
    coverage = {
        "flagged_entities": 47,
        "entities_scanned": 140000,
        "shown_entities": 47,
    }
    
    top_rows = [
        {
            "Organization": "TEST CHARITY INC",
            "Rules triggered": 5,
            "Province": "ON",
            "Federal funding": 250000,
        }
    ]
    
    breakdown_rows = [
        {"Rule": "High dependency", "Count": 35},
        {"Rule": "Zero program spend", "Count": 28},
    ]
    
    summary = _fetch_scan_summary_placeholder(
        "User-Defined Rules",
        coverage,
        top_rows,
        breakdown_rows,
    )
    
    print(f"\nGenerated summary:\n{summary}")
    return True


if __name__ == "__main__":
    print("FundTrace LLM Integration Test")
    print("="*60)
    
    # Check environment variables
    print("\nChecking environment configuration...")
    use_bedrock = os.getenv("USE_BEDROCK", "").lower() == "true"
    print(f"USE_BEDROCK: {use_bedrock}")
    
    if use_bedrock:
        print(f"AWS_DEFAULT_REGION: {os.getenv('AWS_DEFAULT_REGION', 'not set')}")
        print(f"AWS_ACCESS_KEY_ID: {'set' if os.getenv('AWS_ACCESS_KEY_ID') else 'not set'}")
        print(f"AWS_SECRET_ACCESS_KEY: {'set' if os.getenv('AWS_SECRET_ACCESS_KEY') else 'not set'}")
        print(f"AWS_SESSION_TOKEN: {'set' if os.getenv('AWS_SESSION_TOKEN') else 'not set'}")
        print(f"BEDROCK_MODEL: {os.getenv('BEDROCK_MODEL', 'not set')}")
    else:
        print(f"ANTHROPIC_API_KEY: {'set' if os.getenv('ANTHROPIC_API_KEY') else 'not set'}")
    
    print("\n" + "="*60)
    
    # Run tests
    success = True
    
    try:
        if not test_llm_client():
            success = False
    except Exception as e:
        print(f"❌ LLM client test failed with error: {e}")
        success = False
    
    try:
        if not test_scan_summary():
            success = False
    except Exception as e:
        print(f"❌ Scan summary test failed with error: {e}")
        success = False
    
    print("\n" + "="*60)
    if success:
        print("✓ All tests passed!")
    else:
        print("❌ Some tests failed - check output above")
    print("="*60)
