#!/bin/sh

materialize_runtime_credential() {
    value_name="$1"
    file_name="$2"
    target_name="$3"

    eval "value_is_set=\${${value_name}+set}"
    eval "file_is_set=\${${file_name}+set}"
    eval "value=\${${value_name}-}"
    eval "existing_file=\${${file_name}-}"

    if [ "$value_is_set" = "set" ] && [ "$file_is_set" = "set" ]; then
        printf 'runtime credential %s has ambiguous inline and file sources\n' "$value_name" >&2
        return 1
    fi

    if [ "$file_is_set" = "set" ]; then
        if [ -z "$existing_file" ] || [ ! -s "$existing_file" ]; then
            printf 'runtime credential file %s is missing or empty\n' "$file_name" >&2
            return 1
        fi
        return 0
    fi

    if [ "$value_is_set" != "set" ]; then
        return 0
    fi
    if [ -z "$value" ]; then
        printf 'runtime credential %s must not be empty\n' "$value_name" >&2
        return 1
    fi

    secret_dir="${JOYSAFETER_RUNTIME_SECRET_DIR:-/tmp/.joysafeter-runtime-secrets}"
    mkdir -p "$secret_dir"
    chmod 700 "$secret_dir"
    target="$secret_dir/$target_name"
    umask 077
    printf '%s' "$value" > "$target"
    export "$file_name=$target"
    unset "$value_name"
}

prepare_runtime_credentials() {
    materialize_runtime_credential \
        JOYSAFETER_RUNNER_TOKEN \
        JOYSAFETER_RUNNER_TOKEN_FILE \
        runner-session-token || return 1
    materialize_runtime_credential \
        JOYSAFETER_EGRESS_PROXY_TOKEN \
        JOYSAFETER_EGRESS_PROXY_TOKEN_FILE \
        egress-proxy-token || return 1
}
