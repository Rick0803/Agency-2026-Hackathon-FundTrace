# FundTrace LLM Integration - Deployment Checklist

## Pre-Deployment Verification

### 1. Environment Configuration
- [ ] Verify `.env` file exists in `Proto/` directory
- [ ] Confirm `USE_BEDROCK=true` is set
- [ ] Verify AWS credentials are present:
  - [ ] `AWS_DEFAULT_REGION`
  - [ ] `AWS_ACCESS_KEY_ID`
  - [ ] `AWS_SECRET_ACCESS_KEY`
  - [ ] `AWS_SESSION_TOKEN`
  - [ ] `BEDROCK_MODEL`

### 2. Dependencies
- [ ] Verify `boto3` is installed: `pip list | grep boto3`
- [ ] Verify `anthropic` is installed: `pip list | grep anthropic`
- [ ] If missing, install: `pip install boto3 anthropic`

### 3. Test LLM Integration
```bash
cd Proto
python test_llm_integration.py
```
Expected output:
- ✓ LLM client initialized successfully
- ✓ LLM call successful
- ✓ Generated summary appears
- ✓ All tests passed!

### 4. Files Modified (Review Changes)
- [ ] `Proto/agent/llm_client.py` (NEW)
- [ ] `Proto/views/fetch.py` (MODIFIED)
- [ ] `Proto/views/analyze.py` (MODIFIED)
- [ ] `Proto/views/report.py` (MODIFIED)
- [ ] `Proto/agent/orchestrator.py` (MODIFIED)

### 5. Verify No Breaking Changes
- [ ] Run the Streamlit app: `streamlit run Proto/app.py`
- [ ] Navigate to Fetch page → Run a scan → Verify AI Summary appears
- [ ] Navigate to Analyze page → Verify Analysis Summary appears
- [ ] Navigate to Report page → Dashboard → Verify Narrative Brief section
- [ ] Navigate to Report page → Business Report → Generate report → Verify output

## Deployment Steps

### Step 1: Backup Current State
```bash
git add -A
git commit -m "Backup before LLM integration deployment"
```

### Step 2: Deploy Changes
The changes are already in place. No additional deployment needed.

### Step 3: Restart Application
```bash
# If running in a container or service, restart it
# If running locally:
streamlit run Proto/app.py
```

### Step 4: Smoke Test
1. Open the app in browser
2. Navigate through all 4 pages
3. Verify no errors in console
4. Test each LLM use case:
   - Fetch → Run scan → Check AI Summary
   - Analyze → Check Analysis Summary
   - Report → Dashboard → Check Narrative Brief
   - Report → Business Report → Generate → Check output

## Troubleshooting

### Issue: "LLM client initialization failed"
**Cause**: Missing or invalid AWS credentials
**Solution**: 
1. Check `.env` file has all required AWS variables
2. Verify credentials are not expired (Workshop Studio credentials expire)
3. Get fresh credentials from Workshop Studio "Get credentials" button
4. Update `.env` with new credentials

### Issue: "LLM call failed - no response received"
**Cause**: Network error, rate limit, or invalid model ID
**Solution**:
1. Check internet connectivity
2. Verify `BEDROCK_MODEL` matches available models in your region
3. Check AWS CloudWatch logs for detailed error messages
4. Try again after a few seconds (may be rate limited)

### Issue: App shows deterministic output instead of LLM output
**Cause**: LLM call failed silently, graceful fallback activated
**Solution**:
1. This is expected behavior when LLM unavailable
2. Check console/logs for error messages
3. Verify credentials and try again
4. If persistent, check AWS service health

### Issue: JSON parsing error in business report
**Cause**: LLM returned malformed JSON
**Solution**:
1. This triggers automatic fallback to deterministic output
2. No action needed - app continues working
3. If frequent, consider adjusting prompt or increasing max_tokens

## Rollback Plan

If LLM integration causes issues:

### Option 1: Disable LLM (Keep Code)
Set in `.env`:
```bash
USE_BEDROCK=false
ANTHROPIC_API_KEY=  # Leave empty
```
App will use deterministic fallback for all LLM calls.

### Option 2: Revert Code Changes
```bash
git revert HEAD
git push
```

## Monitoring

### Key Metrics to Watch
1. **Token Usage**: Monitor Bedrock token consumption
2. **Response Times**: LLM calls add 1-3 seconds per request
3. **Error Rates**: Check for failed LLM calls in logs
4. **Fallback Rate**: How often deterministic fallback is used

### AWS Bedrock Monitoring
- CloudWatch Logs: `/aws/bedrock/modelinvocations`
- CloudWatch Metrics: `InvocationCount`, `InvocationLatency`, `InvocationErrors`

## Success Criteria

✅ All 4 LLM use cases working:
1. Fetch scan summaries generate natural language
2. Analyze summaries highlight key findings
3. Entity narrative briefs provide context
4. Business reports follow briefing note format

✅ Graceful degradation working:
- App continues functioning when LLM unavailable
- No crashes or error pages
- Deterministic fallback provides reasonable output

✅ Performance acceptable:
- Scan summary: < 3 seconds
- Analyze summary: < 3 seconds
- Narrative brief: < 5 seconds
- Business report: < 8 seconds

## Post-Deployment

### Immediate (First Hour)
- [ ] Monitor error logs
- [ ] Test all 4 LLM use cases
- [ ] Verify token usage is reasonable
- [ ] Check response times

### Short-term (First Day)
- [ ] Gather user feedback on LLM output quality
- [ ] Monitor AWS costs
- [ ] Tune prompts if needed
- [ ] Document any issues

### Long-term (After Hackathon)
- [ ] Review token usage patterns
- [ ] Optimize prompts for cost/quality
- [ ] Consider caching frequent queries
- [ ] Evaluate alternative models if needed

## Contact

For issues or questions:
- Check `LLM_INTEGRATION_SUMMARY.md` for implementation details
- Review code comments in modified files
- Test with `test_llm_integration.py`
