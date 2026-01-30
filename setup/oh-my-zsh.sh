#!/usr/bin/env bash
set -eo pipefail

INSTALL_OH_MYS="true"
USERNAME=${SUDO_USER}
if [ "${USERNAME}" = "root" ]; then
    user_rc_path="/root"
else
    user_rc_path="/home/${USERNAME}"
fi
group_name="${USERNAME}"

if [ "$(id -u)" -ne 0 ]; then
    echo -e 'Script must be run as root. Use sudo, su, or add "USER root" to your Dockerfile before running this script.'
    exit 1
fi

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
    PROMPT+='$([ "$(git config --get codespaces-theme.hide-status 2>/dev/null)" != 1 ] && git_prompt_info)' # Git status
    PROMPT+='%{$fg[white]%}$ %{$reset_color%}'
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
    template_path="${oh_my_install_dir}/templates/zshrc.zsh-template"
    user_rc_file="${user_rc_path}/.zshrc"
    umask g-w,o-w
    mkdir -p "${oh_my_install_dir}"
    git clone --depth=1 \
        -c core.eol=lf \
        -c core.autocrlf=false \
        -c fsck.zeroPaddedFilemode=ignore \
        -c fetch.fsck.zeroPaddedFilemode=ignore \
        -c receive.fsck.zeroPaddedFilemode=ignore \
        "https://github.com/ohmyzsh/ohmyzsh" "${oh_my_install_dir}" 2>&1
    # do not replace .zshrc if it already exists
    if [ ! -f "${user_rc_file}" ]; then
        echo -e "$(cat "${template_path}")\nDISABLE_AUTO_UPDATE=true\nDISABLE_UPDATE_PROMPT=true" > "${user_rc_file}"
    fi
    sed -i -e 's/ZSH_THEME=.*/ZSH_THEME="codespaces"/g' "${user_rc_file}"
    mkdir -p "${oh_my_install_dir}"/custom/themes
    echo "${codespaces_zsh}" > "${oh_my_install_dir}/custom/themes/codespaces.zsh-theme"
    # Shrink git while still enabling updates
    cd "${oh_my_install_dir}"
    git repack -a -d -f --depth=1 --window=1
    # Copy to non-root user if one is specified
    if [ "${USERNAME}" != "root" ]; then
        cp -rf "${user_rc_file}" "${oh_my_install_dir}" /root
        chown -R "${USERNAME}":"${group_name}" "${user_rc_path}"
    fi
fi
