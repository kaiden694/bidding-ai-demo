{{/*
展开 chart 名称
*/}}
{{- define "sbaw.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
展开完整名称（含 release），用于资源命名
*/}}
{{- define "sbaw.fullname" -}}
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
{{- end -}}

{{/*
chart 名称与版本标签
*/}}
{{- define "sbaw.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
通用标签（labels）：所有资源统一使用
*/}}
{{- define "sbaw.labels" -}}
helm.sh/chart: {{ include "sbaw.chart" . }}
{{ include "sbaw.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{/*
选择器标签（selectorLabels）：用于 Service 选择 Pod
*/}}
{{- define "sbaw.selectorLabels" -}}
app.kubernetes.io/name: {{ include "sbaw.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/*
带组件标签的选择器：用于区分 backend/frontend/celery 等组件
参数: .ctx (上下文) .component (组件名)
用法: {{ include "sbaw.componentSelectorLabels" (dict "ctx" . "component" "backend") }}
*/}}
{{- define "sbaw.componentSelectorLabels" -}}
app.kubernetes.io/name: {{ include "sbaw.name" .ctx }}
app.kubernetes.io/instance: {{ .ctx.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{/*
带组件标签的完整标签
*/}}
{{- define "sbaw.componentLabels" -}}
helm.sh/chart: {{ include "sbaw.chart" .ctx }}
{{ include "sbaw.componentSelectorLabels" . }}
app.kubernetes.io/version: {{ .ctx.Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .ctx.Release.Service }}
{{- end -}}

{{/*
镜像拉取凭据
*/}}
{{- define "sbaw.imagePullSecrets" -}}
{{- with .Values.imagePullSecrets -}}
imagePullSecrets:
{{- toYaml . | nindent 0 -}}
{{- end -}}
{{- end -}}

{{/*
生成镜像地址 repository:tag
参数: .image (包含 repository / tag 的对象)
*/}}
{{- define "sbaw.image" -}}
{{- printf "%s:%s" .repository .tag -}}
{{- end -}}

{{/*
安全上下文
*/}}
{{- define "sbaw.securityContext" -}}
{{- with .Values.securityContext -}}
securityContext:
{{- toYaml . | nindent 2 -}}
{{- end -}}
{{- end -}}

{{/*
Pod 安全上下文
*/}}
{{- define "sbaw.podSecurityContext" -}}
{{- with .Values.podSecurityContext -}}
securityContext:
{{- toYaml . | nindent 2 -}}
{{- end -}}
{{- end -}}

{{/*
公共节点选择 / 亲和 / 容忍
*/}}
{{- define "sbaw.nodeSelector" -}}
{{- with .Values.nodeSelector -}}
nodeSelector:
{{- toYaml . | nindent 2 -}}
{{- end -}}
{{- end -}}

{{- define "sbaw.tolerations" -}}
{{- with .Values.tolerations -}}
tolerations:
{{- toYaml . | nindent 2 -}}
{{- end -}}
{{- end -}}

{{- define "sbaw.affinity" -}}
{{- with .Values.affinity -}}
affinity:
{{- toYaml . | nindent 2 -}}
{{- end -}}
{{- end -}}

{{/*
构造 Redis URL（含可选密码）
host 使用 Helm 生成的 redis Service 名，确保与 redis-statefulset.yaml 一致
*/}}
{{- define "sbaw.redisUrl" -}}
{{- $redisHost := printf "%s-redis" (include "sbaw.fullname" .) -}}
{{- if .Values.redis.password -}}
{{- printf "redis://:%s@%s:%d/%s" .Values.redis.password $redisHost (int .Values.redis.port) .Values.redis.db -}}
{{- else -}}
{{- printf "redis://%s:%d/%s" $redisHost (int .Values.redis.port) .Values.redis.db -}}
{{- end -}}
{{- end -}}

{{/*
构造 Celery broker URL
*/}}
{{- define "sbaw.celeryBrokerUrl" -}}
{{- $redisHost := printf "%s-redis" (include "sbaw.fullname" .) -}}
{{- if .Values.redis.password -}}
{{- printf "redis://:%s@%s:%d/%s" .Values.redis.password $redisHost (int .Values.redis.port) .Values.redis.brokerDb -}}
{{- else -}}
{{- printf "redis://%s:%d/%s" $redisHost (int .Values.redis.port) .Values.redis.brokerDb -}}
{{- end -}}
{{- end -}}

{{/*
构造 Celery result backend URL
*/}}
{{- define "sbaw.celeryResultBackend" -}}
{{- $redisHost := printf "%s-redis" (include "sbaw.fullname" .) -}}
{{- if .Values.redis.password -}}
{{- printf "redis://:%s@%s:%d/%s" .Values.redis.password $redisHost (int .Values.redis.port) .Values.redis.backendDb -}}
{{- else -}}
{{- printf "redis://%s:%d/%s" $redisHost (int .Values.redis.port) .Values.redis.backendDb -}}
{{- end -}}
{{- end -}}
