pipeline {
  agent any

  environment {
    AWS_DEFAULT_REGION = "${env.AWS_DEFAULT_REGION ?: 'us-east-1'}"
    BUILD_ID = "${env.BUILD_NUMBER}"
  }

  stages {
    stage('Checkout') {
      steps {
        checkout scm
      }
    }

    stage('Build image') {
      steps {
        sh 'docker compose build detector'
      }
    }

    stage('Push to ECR') {
      when {
        allOf {
          expression { return env.ECR_REGISTRY?.trim() }
          expression { return env.ECR_REPOSITORY?.trim() }
        }
      }
      steps {
        sh """
          export CAR_DETECTOR_IMAGE="${env.ECR_REGISTRY}/${env.ECR_REPOSITORY}:${env.BUILD_NUMBER}"
          aws ecr get-login-password --region ${env.AWS_DEFAULT_REGION} \\
            | docker login --username AWS --password-stdin ${env.ECR_REGISTRY}
          docker compose build detector
          docker compose push detector
        """
      }
    }

    stage('Run detector (S3)') {
      steps {
        sh 'docker compose run --rm detector'
      }
    }
  }

  post {
    always {
      sh 'docker compose down --remove-orphans || true'
    }
  }
}
