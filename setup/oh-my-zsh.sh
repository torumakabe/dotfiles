#!/usr/bin/env bash
#
# Reffered to: https://github.com/microsoft/vscode-dev-containers/blob/main/containers/codespaces-linux/.devcontainer/library-scripts/common-debian.sh

set -eo pipefail

INSTALL_OH_MYS="true"
user_rc_path="${HOME}/${USERNAME}"

codespaces_zsh="$(cat \
<<'EOF'
# Codespaces zsh prompt theme
__zsh_prompt() {
    local prompt_username
    if [ ! -z "${GITHUB_USER}" ]; then
        prompt_username="@${GITHUB_USER}"
    else
        prompt_username="%n"
    fi
    PROMPT="%{$fg[green]%}${prompt_username} %(?:%{$reset_color%}➜ :%{$fg_bold[red]%}➜ )" # User/exit code arrow
    PROMPT+='%{$fg_bold[blue]%}%(5~|%-1~/…/%3~|%4~)%{$reset_color%} ' # cwd
    PROMPT+='$(git_prompt_info)%{$fg[white]%}$ %{$reset_color%}' # Git status
    unset -f __zsh_prompt
}
ZSH_THEME_GIT_PROMPT_PREFIX="%{$fg_bold[cyan]%}(%{$fg_bold[red]%}"
ZSH_THEME_GIT_PROMPT_SUFFIX="%{$reset_color%} "
ZSH_THEME_GIT_PROMPT_DIRTY=" %{$fg_bold[yellow]%}✗%{$fg_bold[cyan]%})"
ZSH_THEME_GIT_PROMPT_CLEAN="%{$fg_bold[cyan]%})"
__zsh_prompt
EOF
)"

oh_my_install_dir="${user_rc_path}/.oh-my-zsh"
if [ ! -d "${oh_my_install_dir}" ] && [ "${INSTALL_OH_MYS}" = "true" ]; then
    umask g-w,o-w
    mkdir -p "${oh_my_install_dir}"
    git clone --depth=1 \
        -c core.eol=lf \
        -c core.autocrlf=false \
        -c fsck.zeroPaddedFilemode=ignore \
        -c fetch.fsck.zeroPaddedFilemode=ignore \
        -c receive.fsck.zeroPaddedFilemode=ignore \
        "https://github.com/ohmyzsh/ohmyzsh" "${oh_my_install_dir}" 2>&1
    mkdir -p "${oh_my_install_dir}/custom/themes"
    echo "${codespaces_zsh}" > "${oh_my_install_dir}/custom/themes/codespaces.zsh-theme"
    # Shrink git while still enabling updates
    cd "${oh_my_install_dir}"
    git repack -a -d -f --depth=1 --window=1
fi
