#!/bin/sh
set -eu

fail() {
    printf '%s\n' "$1" >&2
    exit 1
}

[ -n "${BACKEND_HOST:-}" ] || fail "BACKEND_HOST is required."
[ -n "${CHECKOUT_API_TOKEN:-}" ] || fail "CHECKOUT_API_TOKEN is required."
[ -n "${CHECKOUT_UI_HTPASSWD:-}" ] || fail "CHECKOUT_UI_HTPASSWD is required."

case "$BACKEND_HOST" in
    *[!a-zA-Z0-9.-]* | .* | *. | -* | *-)
        fail "BACKEND_HOST must be a DNS hostname, without a scheme, port, or path." ;;
esac
case "$CHECKOUT_API_TOKEN" in
    *[!a-zA-Z0-9._~+/=-]*)
        fail "CHECKOUT_API_TOKEN must contain only token-safe characters." ;;
esac

printf '%s\n' "$CHECKOUT_UI_HTPASSWD" | awk -F: '
    NF != 2 || $1 !~ /^[a-zA-Z0-9_.@-]+$/ || $2 !~ /^\$(2[aby]|apr1|5|6)\$/ { exit 1 }
    END { if (NR == 0) exit 1 }
' || fail "CHECKOUT_UI_HTPASSWD must contain username:password-hash entries."

umask 077
printf '%s\n' "$CHECKOUT_UI_HTPASSWD" > /etc/nginx/checkout.htpasswd
chown root:nginx /etc/nginx/checkout.htpasswd
chmod 640 /etc/nginx/checkout.htpasswd
envsubst '${BACKEND_HOST} ${CHECKOUT_API_TOKEN}' \
    < /opt/checkout/default.conf.template > /etc/nginx/conf.d/default.conf
unset CHECKOUT_UI_HTPASSWD CHECKOUT_API_TOKEN
exec "$@"
