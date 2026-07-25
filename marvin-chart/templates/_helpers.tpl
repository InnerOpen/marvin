{{/*
Expand the name of the chart.
*/}}
{{- define "marvin.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "marvin.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "marvin.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "marvin.labels" -}}
helm.sh/chart: {{ include "marvin.chart" . }}
{{ include "marvin.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "marvin.selectorLabels" -}}
app.kubernetes.io/name: {{ include "marvin.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "marvin.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "marvin.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Create the name of the persistent volume claim
*/}}
{{- define "marvin.pvcName" -}}
{{- if .Values.persistence.existingClaim }}
{{- .Values.persistence.existingClaim }}
{{- else }}
{{- printf "%s-data" (include "marvin.fullname" .) }}
{{- end }}
{{- end }}

{{/*
Return the appropriate apiVersion for deployment
*/}}
{{- define "marvin.deployment.apiVersion" -}}
{{- if .Capabilities.APIVersions.Has "apps.openshift.io/v1" -}}
apps.openshift.io/v1
{{- else -}}
apps/v1
{{- end -}}
{{- end -}}

{{/*
Return the appropriate kind for deployment
*/}}
{{- define "marvin.deployment.kind" -}}
{{- if .Capabilities.APIVersions.Has "apps.openshift.io/v1" -}}
DeploymentConfig
{{- else -}}
Deployment
{{- end -}}
{{- end -}}

{{/*
Split-mode image references. Backend/frontend default to <image.repository>-backend / -frontend at
image.tag (falling back to the chart appVersion), and can be overridden via split.<component>.image.
*/}}
{{- define "marvin.backendImage" -}}
{{- $repo := .Values.split.backend.image.repository | default (printf "%s-backend" .Values.image.repository) -}}
{{- $tag := .Values.split.backend.image.tag | default .Values.image.tag | default .Chart.AppVersion -}}
{{- printf "%s:%s" $repo $tag -}}
{{- end -}}

{{- define "marvin.frontendImage" -}}
{{- $repo := .Values.split.frontend.image.repository | default (printf "%s-frontend" .Values.image.repository) -}}
{{- $tag := .Values.split.frontend.image.tag | default .Values.image.tag | default .Chart.AppVersion -}}
{{- printf "%s:%s" $repo $tag -}}
{{- end -}}

{{/*
Shared API environment, sourced from the ConfigMap and Secret. Used by the combined container and
the split backend. Frontend-only variables (FRONTEND_PORT, PUBLIC_MARVIN_API_URL, MARVIN_API_URL)
are added by each caller. Keep in step with configmap.yaml / secret.yaml.
*/}}
{{- define "marvin.apiEnv" -}}
- name: PRODUCTION
  valueFrom:
    configMapKeyRef:
      name: {{ include "marvin.fullname" . }}
      key: production
- name: ALLOW_SIGNUP
  valueFrom:
    configMapKeyRef:
      name: {{ include "marvin.fullname" . }}
      key: allowSignup
- name: LOG_LEVEL
  valueFrom:
    configMapKeyRef:
      name: {{ include "marvin.fullname" . }}
      key: logLevel
- name: DB_ENGINE
  valueFrom:
    configMapKeyRef:
      name: {{ include "marvin.fullname" . }}
      key: dbEngine
- name: DATA_DIR
  valueFrom:
    configMapKeyRef:
      name: {{ include "marvin.fullname" . }}
      key: dataDir
- name: API_PORT
  valueFrom:
    configMapKeyRef:
      name: {{ include "marvin.fullname" . }}
      key: apiPort
- name: API_HOST
  valueFrom:
    configMapKeyRef:
      name: {{ include "marvin.fullname" . }}
      key: apiHost
- name: SMTP_HOST
  valueFrom:
    secretKeyRef:
      name: {{ include "marvin.fullname" . }}
      key: smtpHost
- name: SMTP_PORT
  valueFrom:
    secretKeyRef:
      name: {{ include "marvin.fullname" . }}
      key: smtpPort
- name: SMTP_USER
  valueFrom:
    secretKeyRef:
      name: {{ include "marvin.fullname" . }}
      key: smtpUser
      optional: true
- name: SMTP_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ include "marvin.fullname" . }}
      key: smtpPassword
      optional: true
- name: SMTP_FROM_EMAIL
  valueFrom:
    secretKeyRef:
      name: {{ include "marvin.fullname" . }}
      key: smtpFromEmail
- name: JWT_SECRET
  valueFrom:
    secretKeyRef:
      name: {{ include "marvin.fullname" . }}
      key: jwtSecret
{{- end -}}
