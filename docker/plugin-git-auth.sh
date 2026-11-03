# Sourced (`. /plugin-git-auth.sh`) by the Dockerfile's `uv` steps so git can fetch a PRIVATE plugin repo pinned by tag in pyproject's `plugins`
# group. Public plugins need nothing. The credential is a GitHub token with read access to the private plugin repos, given to the build as the
# BuildKit secret `plugin_git_token` (CI: the PLUGIN_GIT_TOKEN Actions secret, e.g.
#   pass show git/https/github.com/jmashburn | head -n1 | gh secret set PLUGIN_GIT_TOKEN -R InnerOpen/marvin
# ; prefer a fine-grained token limited to the plugin repos, contents: read). With no secret (a fork, a local build of public pins only) this does
# nothing. The token lives only under /run/secrets for the one RUN step and is sent as an HTTP header for the listed repos only; it is never put in a
# URL or written into an image layer.
KEY="${PLUGIN_GIT_TOKEN_FILE:-/run/secrets/plugin_git_token}"
# Private plugin repos (names under github.com/InnerOpen), space separated. Public plugins must NOT be listed.
PRIVATE_PLUGIN_REPOS="marvin-integration-elevenlabs"

if [ -s "$KEY" ]; then
    _auth="$(printf 'x-access-token:%s' "$(cat "$KEY")" | base64 -w0)"
    _n=0
    for _repo in $PRIVATE_PLUGIN_REPOS; do
        eval "export GIT_CONFIG_KEY_$_n='http.https://github.com/InnerOpen/$_repo.extraheader'"
        eval "export GIT_CONFIG_VALUE_$_n='AUTHORIZATION: basic $_auth'"
        _n=$((_n + 1))
    done
    export GIT_CONFIG_COUNT="$_n"
    unset _auth
fi
