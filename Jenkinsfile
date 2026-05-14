pipeline {
  agent any

  parameters {
    string(name: 'S3_BUCKET', defaultValue: '', description: 'Required — S3 bucket for video, labels, and metrics output')
    string(name: 'S3_VIDEO_KEY', defaultValue: 'video.mp4', description: 'S3 object key for input video')
    string(name: 'S3_LABELS_KEY', defaultValue: 'labels.json', description: 'S3 object key for labels JSON')
    string(name: 'AWS_DEFAULT_REGION', defaultValue: 'eu-west-1', description: 'AWS region for S3 and ECR')
    string(name: 'AWS_PROFILE', defaultValue: 'default', description: 'Profile name inside ~/.aws mounted into the container')
    string(name: 'MIN_PRECISION', defaultValue: '', description: 'Optional — fail build if global box precision is below this (empty = disabled)')
    string(name: 'MIN_RECALL', defaultValue: '', description: 'Optional — fail build if global box recall is below this (empty = disabled)')
    string(name: 'MIN_ACCURACY', defaultValue: '', description: 'Optional — fail build if frame car-presence accuracy is below this (empty = disabled)')
    string(name: 'METRICS_GATE_BOX_METRICS', defaultValue: 'global', description: 'global or labeled — which metrics MIN_PRECISION/MIN_RECALL compare against')
  }

  environment {
    // Prefer Build Parameters; if empty, inherit Jenkins global / node env (Option B).
    S3_BUCKET = "${params.S3_BUCKET?.trim() ? params.S3_BUCKET.trim() : (env.S3_BUCKET ?: '')}"
    S3_VIDEO_KEY = "${params.S3_VIDEO_KEY?.trim() ? params.S3_VIDEO_KEY.trim() : (env.S3_VIDEO_KEY ?: 'video.mp4')}"
    S3_LABELS_KEY = "${params.S3_LABELS_KEY?.trim() ? params.S3_LABELS_KEY.trim() : (env.S3_LABELS_KEY ?: 'labels.json')}"
    AWS_DEFAULT_REGION = "${params.AWS_DEFAULT_REGION?.trim() ? params.AWS_DEFAULT_REGION.trim() : (env.AWS_DEFAULT_REGION ?: 'eu-west-1')}"
    AWS_PROFILE = "${params.AWS_PROFILE?.trim() ? params.AWS_PROFILE.trim() : (env.AWS_PROFILE ?: 'default')}"
    MIN_PRECISION = "${params.MIN_PRECISION?.trim() ? params.MIN_PRECISION.trim() : (env.MIN_PRECISION ?: '')}"
    MIN_RECALL = "${params.MIN_RECALL?.trim() ? params.MIN_RECALL.trim() : (env.MIN_RECALL ?: '')}"
    MIN_ACCURACY = "${params.MIN_ACCURACY?.trim() ? params.MIN_ACCURACY.trim() : (env.MIN_ACCURACY ?: '')}"
    METRICS_GATE_BOX_METRICS = "${params.METRICS_GATE_BOX_METRICS?.trim() ? params.METRICS_GATE_BOX_METRICS.trim() : (env.METRICS_GATE_BOX_METRICS ?: 'global')}"
    BUILD_ID = "${env.BUILD_NUMBER}"
  }

  stages {
    stage('Validate') {
      steps {
        script {
          if (!env.S3_BUCKET?.trim()) {
            error 'S3_BUCKET is empty. Set it under Manage Jenkins → System → Global properties → Environment variables, or use Build with Parameters / "בנייה עם פרמטרים".'
          }
        }
      }
    }

    stage('Checkout') {
      steps {
        checkout scm
      }
    }

    stage('Build image') {
      steps {
        script {
          if (isUnix()) {
            sh 'docker compose build detector'
          } else {
            bat 'docker compose build detector'
          }
        }
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
        script {
          if (isUnix()) {
            sh """
              export CAR_DETECTOR_IMAGE="${env.ECR_REGISTRY}/${env.ECR_REPOSITORY}:${env.BUILD_NUMBER}"
              aws ecr get-login-password --region ${env.AWS_DEFAULT_REGION} \\
                | docker login --username AWS --password-stdin ${env.ECR_REGISTRY}
              docker compose build detector
              docker compose push detector
            """
          } else {
            bat """
              set "CAR_DETECTOR_IMAGE=${env.ECR_REGISTRY}/${env.ECR_REPOSITORY}:${env.BUILD_NUMBER}"
              aws ecr get-login-password --region ${env.AWS_DEFAULT_REGION} | docker login --username AWS --password-stdin ${env.ECR_REGISTRY}
              docker compose build detector
              docker compose push detector
            """
          }
        }
      }
    }

    stage('Run detector (S3)') {
      steps {
        script {
          if (isUnix()) {
            sh 'docker compose run --rm detector'
          } else {
            bat 'docker compose run --rm detector'
          }
        }
      }
    }
  }

  post {
    always {
      script {
        if (isUnix()) {
          sh 'docker compose down --remove-orphans || true'
        } else {
          bat(returnStatus: true, script: 'docker compose down --remove-orphans')
        }
      }
    }
  }
}
