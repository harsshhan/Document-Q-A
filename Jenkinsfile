pipeline {
    agent any

    environment {
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
                    trivy image --severity HIGH,CRITICAL --ignore-unfixed document-qa-backend:latest
                    trivy image --severity HIGH,CRITICAL --ignore-unfixed document-qa-frontend:latest
                '''
            }
        }

        stage('Push Images to AWS ECR') {
            steps {
                script {
                    def registry = '339712882309.dkr.ecr.ap-south-1.amazonaws.com'

                    sh """
                        aws ecr get-login-password --region ap-south-1 |
                        docker login --username AWS --password-stdin ${registry}

                        docker tag document-qa-backend:latest ${registry}/document-qa-backend:latest
                        docker tag document-qa-frontend:latest ${registry}/document-qa-frontend:latest

                        docker push ${registry}/document-qa-backend:latest
                        docker push ${registry}/document-qa-frontend:latest
                    """
                }
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