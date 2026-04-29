#!/bin/bash
# Quick deployment script for FundTrace to AWS App Runner
# Usage: ./deploy.sh

set -e

echo "🚀 FundTrace Deployment Script"
echo "================================"
echo ""

# Check if AWS CLI is installed
if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI is not installed. Please install it first:"
    echo "   https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html"
    exit 1
fi

# Check if AWS is configured
if ! aws sts get-caller-identity &> /dev/null; then
    echo "❌ AWS CLI is not configured. Please run: aws configure"
    exit 1
fi

echo "✅ AWS CLI is configured"
echo ""

# Get AWS account ID
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
AWS_REGION=${AWS_DEFAULT_REGION:-us-west-2}

echo "📋 Deployment Configuration:"
echo "   AWS Account: $AWS_ACCOUNT_ID"
echo "   AWS Region: $AWS_REGION"
echo ""

# Ask for service name
read -p "Enter service name (default: fundtrace-demo): " SERVICE_NAME
SERVICE_NAME=${SERVICE_NAME:-fundtrace-demo}

echo ""
echo "🔧 Deployment Options:"
echo "1. Deploy from GitHub (recommended)"
echo "2. Deploy from local Docker image"
echo "3. Test locally with Docker"
echo ""
read -p "Choose option (1-3): " DEPLOY_OPTION

case $DEPLOY_OPTION in
    1)
        echo ""
        echo "📦 Deploying from GitHub..."
        read -p "Enter your GitHub repository URL: " GITHUB_URL
        read -p "Enter branch name (default: main): " BRANCH_NAME
        BRANCH_NAME=${BRANCH_NAME:-main}
        
        echo ""
        echo "⚠️  You'll need to configure environment variables in AWS Console:"
        echo "   1. Go to: https://console.aws.amazon.com/apprunner/"
        echo "   2. Find your service: $SERVICE_NAME"
        echo "   3. Go to Configuration → Environment variables"
        echo "   4. Add variables from your .env file"
        echo ""
        read -p "Press Enter to open AWS Console..." 
        
        # Open AWS Console
        if [[ "$OSTYPE" == "darwin"* ]]; then
            open "https://console.aws.amazon.com/apprunner/"
        elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
            xdg-open "https://console.aws.amazon.com/apprunner/"
        else
            echo "Please open: https://console.aws.amazon.com/apprunner/"
        fi
        
        echo ""
        echo "✅ Follow the AWS Console wizard to complete deployment"
        echo "   - Select 'Source code repository'"
        echo "   - Connect to GitHub and select: $GITHUB_URL"
        echo "   - Branch: $BRANCH_NAME"
        echo "   - Use configuration file: apprunner.yaml"
        ;;
        
    2)
        echo ""
        echo "🐳 Building and deploying Docker image..."
        
        # Create ECR repository if it doesn't exist
        echo "Creating ECR repository..."
        aws ecr create-repository \
            --repository-name fundtrace \
            --region $AWS_REGION \
            2>/dev/null || echo "Repository already exists"
        
        # Get ECR login
        echo "Logging into ECR..."
        aws ecr get-login-password --region $AWS_REGION | \
            docker login --username AWS --password-stdin \
            $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com
        
        # Build Docker image
        echo "Building Docker image..."
        docker build -t fundtrace:latest .
        
        # Tag image
        echo "Tagging image..."
        docker tag fundtrace:latest \
            $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/fundtrace:latest
        
        # Push to ECR
        echo "Pushing to ECR..."
        docker push $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/fundtrace:latest
        
        echo ""
        echo "✅ Image pushed to ECR"
        echo "   Image URI: $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/fundtrace:latest"
        echo ""
        echo "⚠️  Now create App Runner service in AWS Console:"
        echo "   1. Go to: https://console.aws.amazon.com/apprunner/"
        echo "   2. Create service → Container registry"
        echo "   3. Use image URI above"
        echo "   4. Port: 8080"
        echo "   5. Add environment variables from .env"
        
        # Open AWS Console
        if [[ "$OSTYPE" == "darwin"* ]]; then
            open "https://console.aws.amazon.com/apprunner/"
        elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
            xdg-open "https://console.aws.amazon.com/apprunner/"
        else
            echo "Please open: https://console.aws.amazon.com/apprunner/"
        fi
        ;;
        
    3)
        echo ""
        echo "🧪 Testing locally with Docker..."
        
        # Check if .env exists
        if [ ! -f .env ]; then
            echo "❌ .env file not found. Please create it from .env.example"
            exit 1
        fi
        
        # Build Docker image
        echo "Building Docker image..."
        docker build -t fundtrace:latest .
        
        # Run container
        echo "Starting container..."
        echo "App will be available at: http://localhost:8080"
        echo "Press Ctrl+C to stop"
        echo ""
        
        docker run -p 8080:8080 --env-file .env fundtrace:latest
        ;;
        
    *)
        echo "❌ Invalid option"
        exit 1
        ;;
esac

echo ""
echo "✅ Deployment process initiated!"
echo ""
echo "📚 For detailed instructions, see: DEPLOYMENT_GUIDE.md"
