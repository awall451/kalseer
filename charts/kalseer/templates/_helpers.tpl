{{/* Standard helper boilerplate. */}}

{{- define "kalseer.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "kalseer.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end }}

{{- define "kalseer.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "kalseer.labels" -}}
helm.sh/chart: {{ include "kalseer.chart" . }}
{{ include "kalseer.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "kalseer.selectorLabels" -}}
app.kubernetes.io/name: {{ include "kalseer.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
  Resolve the name of the Secret holding git-sync credentials for the
  private data repo. If the user provides an existing one, use that.
  Otherwise the chart generates "<fullname>-gitsync" (used by both the
  Secret and SealedSecret templates).
*/}}
{{- define "kalseer.gitsyncSecretName" -}}
{{- if .Values.dataSync.existingSecret -}}
{{- .Values.dataSync.existingSecret -}}
{{- else -}}
{{- printf "%s-gitsync" (include "kalseer.fullname" .) -}}
{{- end -}}
{{- end }}

{{/* Whether any git-sync credential source is configured. */}}
{{- define "kalseer.gitsyncHasCreds" -}}
{{- if or .Values.dataSync.existingSecret .Values.dataSync.username .Values.dataSync.password .Values.dataSync.sealed.username .Values.dataSync.sealed.password -}}
true
{{- end -}}
{{- end }}
