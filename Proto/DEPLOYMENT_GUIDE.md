# FundTrace Cloud Deployment Guide

## Overview

This guide covers deploying FundTrace to AWS App Runner for your hackathon demo while maintaining local development capability.

**Estimated Setup Time:** 15-20 minutes  
**Cost:** ~$5-10 for hackathon duration (with AWS credits)  
**Difficulty:** Easy (mostly point-and-click)

---

## Prerequisites

- ✅ AWS Account with credits
- ✅ AWS CLI installed (optional but recommended)
- ✅ Docker installed locally (for testing)
- ✅ Git repository (GitHub recommended)

---

## Deployment Options

### Option 1: AWS App Runner (Recommended - Easiest)
**Best for:** Quick demo deployment, automatic scaling, minimal management

### Option 2: AWS ECS Fargate (Alternative)
**Best for:** More control, integration with other AWS services

### Option 3: AWS EC2 (Not Recommended for Hackathon)
**Best for:** Maximum control, but requires more setup

---

## Option 1: AWS App Runner Deployment (Recommended)

### Step 1: Prepare Your Repository

1. **Push your code to GitHub** (if not already done):
```bash
cd Proto
git init
git add .
git commit -m "Initial commit for cloud deployment"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/fundtrace.git
git push -u origin main
```

2. **Verify required files exist:**
- ✅ `Dockerfile`
- ✅ `requirements.txt`
- ✅ `.dockerignore`
- ✅ `apprunner.yaml`

### Step 2: Set Up AWS App Runner

#### Method A: Using AWS Console (Easiest)

1. **Go to AWS App Runner Console:**
   - Navigate to: https://console.aws.amazon.com/apprunner/
   - Click "Create service"

2. **Configure Source:**
   - **Repository type:** Source code repository
   - **Connect to GitHub:** Click "Add new" and authorize AWS to access your GitHub
   - **Repository:** Select your FundTrace repository
   - **Branch:** `main`
   - **Deployment trigger:** Automatic (deploys on every push)

3. **Configure Build:**
   - **Configuration file:** Use configuration file (apprunner.yaml)
   - Or manually configure:
     - **Runtime:** Python 3
     - **Build command:** `pip install -r requirements.txt`
     - **Start command:** `streamlit run app.py --server.port=8080 --server.address=0.0.0.0`
     - **Port:** 8080

4. **Configure Service:**
   - **Service name:** `fundtrace-demo`
   - **CPU:** 1 vCPU
   - **Memory:** 2 GB
   - **Environment variables:** Click "Add environment variable"
     - Add each variable from your `.env` file:
       ```
       DB_CONNECTION_STRING=postgresql://...
       USE_BEDROCK=true
       AWS_DEFAULT_REGION=us-west-2
       AWS_ACCESS_KEY_ID=...
       AWS_SECRET_ACCESS_KEY=...
       AWS_SESSION_TOKEN=...
       BEDROCK_MODEL=anthropic.claude-opus-4-5-20251101-v1:0
       ```

5. **Configure Auto Scaling (Optional):**
   - **Min instances:** 1
   - **Max instances:** 3
   - **Concurrency:** 100

6. **Review and Create:**
   - Review all settings
   - Click "Create & deploy"
   - Wait 5-10 minutes for deployment

7. **Get Your URL:**
   - Once deployed, you'll see a URL like: `https://abc123.us-west-2.awsapprunner.com`
   - This is your public demo URL!

#### Method B: Using AWS CLI (Faster for Repeat Deployments)

1. **Install AWS CLI** (if not already installed):
```bash
# macOS
brew install awscli

# Windows
# Download from: https://aws.amazon.com/cli/

# Linux
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip
sudo ./aws/install
```

2. **Configure AWS CLI:**
```bash
aws configure
# Enter your AWS Access Key ID
# Enter your AWS Secret Access Key
# Default region: us-west-2
# Default output format: json
```

3. **Create App Runner service:**
```bash
# First, create a source configuration (one-time setup)
aws apprunner create-auto-scaling-configuration \
  --auto-scaling-configuration-name fundtrace-autoscaling \
  --max-concurrency 100 \
  --min-size 1 \
  --max-size 3

# Create the service
aws apprunner create-service \
  --service-name fundtrace-demo \
  --source-configuration '{
    "CodeRepository": {
      "RepositoryUrl": "https://github.com/YOUR_USERNAME/fundtrace",
      "SourceCodeVersion": {
        "Type": "BRANCH",
        "Value": "main"
      },
      "CodeConfiguration": {
        "ConfigurationSource": "API",
        "CodeConfigurationValues": {
          "Runtime": "PYTHON_3",
          "BuildCommand": "pip install -r requirements.txt",
          "StartCommand": "streamlit run app.py --server.port=8080 --server.address=0.0.0.0",
          "Port": "8080",
          "RuntimeEnvironmentVariables": {
            "DB_CONNECTION_STRING": "postgresql://...",
            "USE_BEDROCK": "true",
            "AWS_DEFAULT_REGION": "us-west-2"
          }
        }
      }
    },
    "AutoDeploymentsEnabled": true
  }' \
  --instance-configuration '{
    "Cpu": "1 vCPU",
    "Memory": "2 GB"
  }'
```

4. **Get service URL:**
```bash
aws apprunner describe-service --service-arn YOUR_SERVICE_ARN
# Look for "ServiceUrl" in the output
```

### Step 3: Verify Deployment

1. **Check deployment status:**
   - In AWS Console: App Runner → Services → fundtrace-demo
   - Status should show "Running"

2. **Test your app:**
   - Open the App Runner URL in your browser
   - Verify the app loads correctly
   - Test a few features (Fetch, Analyze, Report)

3. **Check logs (if issues):**
   - In AWS Console: App Runner → Services → fundtrace-demo → Logs
   - Or use CloudWatch Logs

### Step 4: Update Environment Variables (If Needed)

**Via AWS Console:**
1. Go to App Runner → Services → fundtrace-demo
2. Click "Configuration" tab
3. Click "Edit" under "Environment variables"
4. Add/update variables
5. Click "Deploy" to apply changes

**Via AWS CLI:**
```bash
aws apprunner update-service \
  --service-arn YOUR_SERVICE_ARN \
  --source-configuration '{
    "CodeRepository": {
      "CodeConfiguration": {
        "CodeConfigurationValues": {
          "RuntimeEnvironmentVariables": {
            "NEW_VAR": "new_value"
          }
        }
      }
    }
  }'
```

---

## Option 2: Docker Container (Local Testing Before Cloud)

### Test Locally with Docker

1. **Build the Docker image:**
```bash
cd Proto
docker build -t fundtrace:latest .
```

2. **Run the container locally:**
```bash
docker run -p 8080:8080 \
  -e DB_CONNECTION_STRING="postgresql://..." \
  -e USE_BEDROCK="true" \
  -e AWS_DEFAULT_REGION="us-west-2" \
  -e AWS_ACCESS_KEY_ID="..." \
  -e AWS_SECRET_ACCESS_KEY="..." \
  -e AWS_SESSION_TOKEN="..." \
  -e BEDROCK_MODEL="anthropic.claude-opus-4-5-20251101-v1:0" \
  fundtrace:latest
```

3. **Test in browser:**
   - Open: http://localhost:8080
   - Verify app works correctly

4. **Stop the container:**
```bash
docker ps  # Find container ID
docker stop CONTAINER_ID
```

### Push to Amazon ECR (For ECS/Fargate Deployment)

1. **Create ECR repository:**
```bash
aws ecr create-repository --repository-name fundtrace
```

2. **Login to ECR:**
```bash
aws ecr get-login-password --region us-west-2 | \
  docker login --username AWS --password-stdin \
  YOUR_ACCOUNT_ID.dkr.ecr.us-west-2.amazonaws.com
```

3. **Tag and push image:**
```bash
docker tag fundtrace:latest \
  YOUR_ACCOUNT_ID.dkr.ecr.us-west-2.amazonaws.com/fundtrace:latest

docker push \
  YOUR_ACCOUNT_ID.dkr.ecr.us-west-2.amazonaws.com/fundtrace:latest
```

---

## Local Development Workflow (Unchanged)

Your local development workflow remains exactly the same:

```bash
cd Proto
pip install -r requirements.txt
streamlit run app.py
```

**Key Points:**
- ✅ `.env` file is used locally (not committed to git)
- ✅ Cloud uses environment variables configured in App Runner
- ✅ Same codebase works both locally and in cloud
- ✅ Push to GitHub triggers automatic cloud deployment

---

## Environment Variables Management

### Local Development
- Use `.env` file (already configured)
- Never commit `.env` to git

### Cloud Deployment
- Configure in App Runner console or CLI
- Stored securely by AWS
- Can be updated without redeploying code

### Best Practices
1. **Keep `.env.example` updated** with all required variables
2. **Use AWS Secrets Manager** for production (optional for hackathon)
3. **Rotate AWS credentials** after hackathon
4. **Document any new variables** in this guide

---

## Continuous Deployment

### Automatic Deployment (Recommended)

Once set up, deployments are automatic:

1. **Make code changes locally**
2. **Commit and push to GitHub:**
   ```bash
   git add .
   git commit -m "Update feature X"
   git push origin main
   ```
3. **App Runner automatically:**
   - Detects the push
   - Builds new container
   - Deploys to production
   - Takes ~5-10 minutes

### Manual Deployment

If you need to trigger a manual deployment:

**Via Console:**
- App Runner → Services → fundtrace-demo → "Deploy"

**Via CLI:**
```bash
aws apprunner start-deployment --service-arn YOUR_SERVICE_ARN
```

---

## Monitoring & Debugging

### View Logs

**Via Console:**
1. App Runner → Services → fundtrace-demo → Logs
2. Or CloudWatch → Log groups → `/aws/apprunner/fundtrace-demo`

**Via CLI:**
```bash
aws logs tail /aws/apprunner/fundtrace-demo/service --follow
```

### Common Issues

#### Issue: App won't start
**Solution:** Check logs for Python errors, missing dependencies

#### Issue: Database connection fails
**Solution:** Verify `DB_CONNECTION_STRING` is correct and database is publicly accessible

#### Issue: LLM calls fail
**Solution:** Check AWS credentials are valid and not expired

#### Issue: App is slow
**Solution:** Increase CPU/Memory in App Runner configuration

#### Issue: 502 Bad Gateway
**Solution:** App is starting up, wait 2-3 minutes

---

## Cost Optimization

### For Hackathon Demo

**Recommended Configuration:**
- **CPU:** 1 vCPU
- **Memory:** 2 GB
- **Min instances:** 1
- **Max instances:** 2

**Estimated Cost:**
- ~$0.007/hour when running
- ~$0.003/hour when idle
- **Total for 1 week:** ~$5-10

### Cost Saving Tips

1. **Pause when not demoing:**
   ```bash
   aws apprunner pause-service --service-arn YOUR_SERVICE_ARN
   ```

2. **Resume before demo:**
   ```bash
   aws apprunner resume-service --service-arn YOUR_SERVICE_ARN
   ```

3. **Delete after hackathon:**
   ```bash
   aws apprunner delete-service --service-arn YOUR_SERVICE_ARN
   ```

---

## Security Considerations

### For Hackathon (Current Setup)
- ✅ Public URL (no authentication)
- ✅ HTTPS enabled by default
- ✅ Environment variables encrypted at rest
- ⚠️ Database credentials in environment variables

### For Production (Future)
- Add authentication (Streamlit auth or AWS Cognito)
- Use AWS Secrets Manager for credentials
- Enable VPC for database access
- Add WAF for DDoS protection
- Enable CloudWatch alarms

---

## Troubleshooting

### Deployment Fails

1. **Check build logs:**
   - App Runner → Services → fundtrace-demo → Logs → Build logs

2. **Common causes:**
   - Missing dependencies in `requirements.txt`
   - Syntax errors in `Dockerfile`
   - Invalid environment variables

3. **Fix and redeploy:**
   ```bash
   git add .
   git commit -m "Fix deployment issue"
   git push origin main
   ```

### App Crashes After Deployment

1. **Check application logs:**
   - App Runner → Services → fundtrace-demo → Logs → Application logs

2. **Common causes:**
   - Database connection timeout
   - Missing environment variables
   - Out of memory

3. **Increase resources:**
   - Edit service configuration
   - Increase CPU/Memory
   - Redeploy

### Can't Access App

1. **Check service status:**
   - Should show "Running" in green

2. **Check health checks:**
   - App Runner → Services → fundtrace-demo → Health

3. **Verify URL:**
   - Copy exact URL from App Runner console
   - Try in incognito/private browser window

---

## Quick Reference Commands

### Deploy to App Runner
```bash
# Initial setup (one-time)
aws apprunner create-service --cli-input-json file://apprunner-config.json

# Update deployment
git push origin main  # Automatic deployment

# Manual deployment
aws apprunner start-deployment --service-arn YOUR_SERVICE_ARN
```

### Manage Service
```bash
# Pause service (save costs)
aws apprunner pause-service --service-arn YOUR_SERVICE_ARN

# Resume service
aws apprunner resume-service --service-arn YOUR_SERVICE_ARN

# Delete service
aws apprunner delete-service --service-arn YOUR_SERVICE_ARN
```

### View Logs
```bash
# Tail logs
aws logs tail /aws/apprunner/fundtrace-demo/service --follow

# Get service details
aws apprunner describe-service --service-arn YOUR_SERVICE_ARN
```

### Local Testing
```bash
# Run locally
streamlit run app.py

# Test with Docker
docker build -t fundtrace:latest .
docker run -p 8080:8080 --env-file .env fundtrace:latest
```

---

## Demo Day Checklist

### Before Demo
- [ ] Verify app is running: Check App Runner status
- [ ] Test all features: Fetch, Analyze, Report
- [ ] Check LLM is working: Generate a business report
- [ ] Verify data loads: Run a zombie scan
- [ ] Have backup plan: Local version ready if cloud fails
- [ ] Share URL with judges: Copy from App Runner console

### During Demo
- [ ] Use incognito window (fresh session)
- [ ] Have URL bookmarked
- [ ] Monitor CloudWatch logs (optional)
- [ ] Have local version ready as backup

### After Demo
- [ ] Pause service to save costs (optional)
- [ ] Collect feedback
- [ ] Update README with demo URL
- [ ] Consider keeping it running for portfolio

---

## Next Steps

1. **Deploy to App Runner** using Method A (Console) - easiest for first time
2. **Test the deployment** - verify all features work
3. **Share the URL** with your team
4. **Set up monitoring** - enable CloudWatch alarms (optional)
5. **Prepare for demo** - practice the workflow

---

## Support Resources

- **AWS App Runner Docs:** https://docs.aws.amazon.com/apprunner/
- **Streamlit Deployment:** https://docs.streamlit.io/deploy
- **Docker Documentation:** https://docs.docker.com/
- **AWS CLI Reference:** https://docs.aws.amazon.com/cli/

---

## Status

✅ **Ready for deployment**

All configuration files are in place:
- `Dockerfile` - Container configuration
- `.dockerignore` - Build optimization
- `apprunner.yaml` - App Runner configuration
- `.env.example` - Environment variable template

**Estimated deployment time:** 15-20 minutes  
**Estimated cost:** $5-10 for hackathon week  
**Difficulty:** Easy (mostly point-and-click)

Good luck with your hackathon demo! 🚀
