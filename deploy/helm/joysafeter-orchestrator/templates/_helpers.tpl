{{- define "joysafeter.fullname" -}}
joysafeter-orchestrator
{{- end -}}

{{- define "joysafeter.labels" -}}
app: joysafeter-orchestrator
app.kubernetes.io/name: joysafeter-orchestrator
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/environment: {{ .Values.environment }}
{{- end -}}
