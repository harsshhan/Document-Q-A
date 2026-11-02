pipeline {
    agent any

    environment {
        REGISTRY = '339712882309.dkr.ecr.ap-south-1.amazonaws.com'
        BACKEND_IMAGE = 'document-qa-backend'
        FRONTEND_IMAGE = 'document-qa-frontend'
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        stage('Backend Tests') {
            steps {
                dir('backend') {
                    sh '''
                        docker run --rm \
                          -v "$PWD:/app" \
                          -w /app \
                          python:3.12-slim \
                          sh -c "pip install -r requirements.txt && pytest -q"
                    '''
                }
            }
        }

        stage('Frontend Checks') {
            steps {
                dir('frontend') {
                    sh '''
                        docker run --rm \
                          -v "$PWD:/app" \
                          -w /app \
                          node:22-alpine \
                          sh -c "npm ci && npm run lint && npm run build"
                    '''
                }
            }
        }

        stage('Build Docker Images') {
            steps {
                sh '''
                    docker build -t $BACKEND_IMAGE:latest ./backend
                    docker build -t $FRONTEND_IMAGE:latest ./frontend
                '''
            }
        }

        stage('Trivy Security Scan') {
            steps {
                sh '''
                    trivy image --severity HIGH,CRITICAL --ignore-unfixed $BACKEND_IMAGE:latest
                    trivy image --severity HIGH,CRITICAL --ignore-unfixed $FRONTEND_IMAGE:latest
                '''
            }
        }

        stage('Build and Push Multi-Platform Images') {
            steps {
                sh '''
                    REGISTRY=$REGISTRY

                    docker buildx create \
                      --name document-qa-builder \
                      --driver docker-container \
                      --use || docker buildx use document-qa-builder

                    docker buildx inspect --bootstrap

                    aws ecr get-login-password --region ap-south-1 |
                    docker login --username AWS --password-stdin $REGISTRY

                    docker buildx build \
                      --platform linux/amd64,linux/arm64 \
                      -t $REGISTRY/$BACKEND_IMAGE:latest \
                      --push ./backend

                    docker buildx build \
                      --platform linux/amd64,linux/arm64 \
                      -t $REGISTRY/$FRONTEND_IMAGE:latest \
                      --push ./frontend
                '''
            }
        }
    }

    post {
        success {
            echo 'CI Pipeline completed successfully!'
        }
        failure {
            echo 'CI Pipeline failed. Check the logs.'
        }
    }
}