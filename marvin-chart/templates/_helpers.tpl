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
- name: SCHEDULER_INTERVAL_SECONDS
  valueFrom:
    configMapKeyRef:
      name: {{ include "marvin.fullname" . }}
      key: schedulerInterval
- name: CORS_ORIGINS
  valueFrom:
    configMapKeyRef:
      name: {{ include "marvin.fullname" . }}
      key: corsOrigins
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
{{- with include "marvin.postgresEnv" . | trim }}
{{ . }}
{{- end }}
{{- end -}}

{{/*
Database engine guard: only the two engines the app knows.
*/}}
{{- define "marvin.dbEngine" -}}
{{- $engine := .Values.config.dbEngine | default "sqlite" -}}
{{- if not (has $engine (list "sqlite" "postgres")) -}}
{{- fail (printf "config.dbEngine must be sqlite or postgres, not %q" $engine) -}}
{{- end -}}
{{- $engine -}}
{{- end -}}

{{/*
CloudNativePG cluster name (postgres.cluster.name, else "<fullname>-pg") and the Secret holding the
app's connection: postgres.existingSecret, else the "<cluster>-app" Secret CNPG keeps for the owner.
*/}}
{{- define "marvin.pgClusterName" -}}
{{- .Values.postgres.cluster.name | default (printf "%s-pg" (include "marvin.fullname" .)) | trunc 50 | trimSuffix "-" -}}
{{- end -}}

{{- define "marvin.pgSecretName" -}}
{{- if .Values.postgres.existingSecret -}}
{{- .Values.postgres.existingSecret -}}
{{- else if .Values.postgres.cluster.enabled -}}
{{- printf "%s-app" (include "marvin.pgClusterName" .) -}}
{{- else -}}
{{- fail "config.dbEngine=postgres needs postgres.existingSecret, or postgres.cluster.enabled to use the chart's CloudNativePG cluster" -}}
{{- end -}}
{{- end -}}

{{/*
POSTGRES_* for the app (and the backup job) from the connection Secret — nothing with sqlite, so a
sqlite render is unchanged. Keys default to CloudNativePG's <cluster>-app Secret.
*/}}
{{- define "marvin.postgresEnv" -}}
{{- if eq (include "marvin.dbEngine" .) "postgres" }}
{{- $secret := include "marvin.pgSecretName" . }}
{{- $k := .Values.postgres.secretKeys }}
{{- range $env, $key := dict "POSTGRES_SERVER" $k.host "POSTGRES_PORT" $k.port "POSTGRES_USER" $k.username "POSTGRES_PASSWORD" $k.password "POSTGRES_DB" $k.database }}
- name: {{ $env }}
  valueFrom:
    secretKeyRef:
      name: {{ $secret }}
      key: {{ $key }}
{{- end }}
{{- end }}
{{- end -}}

{{/*
Graceful shutdown of the API container (combined, or the split backend). An agent run is one
synchronous request that can take minutes; on a deploy the pod is told to stop (SIGTERM) and killed
outright terminationGracePeriodSeconds later. Kubernetes counts the preStop sleep inside that grace,
so the server's own drain window is what is left after it, less a margin for the app's shutdown
hooks and process exit. A run still going at the deadline is lost; the next process marks it failed
(AI_INTERRUPTED_RUN_SWEEP_DELAY_SECONDS) — only once the draining pod is surely gone, since a rolling
update starts the new pod while the old one is still finishing its runs.
*/}}
{{/*
The API pod's update strategy: the split backend's own when set, else the shared `strategy`.
*/}}
{{- define "marvin.apiStrategy" -}}
{{- $s := .Values.strategy -}}
{{- if and (eq .Values.mode "split") .Values.split.backend.strategy -}}
{{- $s = .Values.split.backend.strategy -}}
{{- end -}}
{{- toYaml $s -}}
{{- end -}}

{{- define "marvin.shutdownEnv" -}}
{{- $grace := int .Values.shutdown.terminationGracePeriodSeconds -}}
{{- $preStop := int .Values.shutdown.preStopSleepSeconds -}}
{{- $exitMargin := 15 -}}{{/* seconds kept for lifespan shutdown + exit after the drain */}}
{{- $sweepMargin := 60 -}}{{/* seconds past the old pod's kill deadline before sweeping its runs */}}
{{- $strategy := include "marvin.apiStrategy" . | fromYaml -}}
- name: GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS
  value: {{ max 1 (sub $grace (add $preStop $exitMargin)) | quote }}
- name: AI_INTERRUPTED_RUN_SWEEP_DELAY_SECONDS
  {{- /* Recreate stops the old pod before the new one starts: none of its runs can still be going. */}}
  value: {{ if eq (toString $strategy.type) "Recreate" }}"0"{{ else }}{{ add $grace $sweepMargin | quote }}{{ end }}
{{- end -}}
