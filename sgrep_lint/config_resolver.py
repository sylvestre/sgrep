import base64
import os
import shutil
import sys
import tarfile
import time
from pathlib import Path
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

import requests
import yaml
from constants import DEFAULT_CONFIG_FILE
from constants import DEFAULT_CONFIG_FOLDER
from constants import DEFAULT_SGREP_CONFIG_NAME
from constants import ID_KEY
from constants import RULES_KEY
from constants import YML_EXTENSIONS
from util import debug_print
from util import is_url
from util import print_error
from util import print_error_exit
from util import print_msg

IN_DOCKER = "SGREP_IN_DOCKER" in os.environ
IN_GH_ACTION = "GITHUB_WORKSPACE" in os.environ
REPO_HOME_DOCKER = "/home/repo/"

TEMPLATE_YAML_URL = (
    "https://raw.githubusercontent.com/returntocorp/sgrep-rules/develop/template.yaml"
)

RULES_REGISTRY = {
    "r2c": "https://github.com/returntocorp/sgrep-rules/tarball/master",
    "r2c-develop": "https://github.com/returntocorp/sgrep-rules/tarball/develop",
}
DEFAULT_REGISTRY_KEY = "r2c"


def manual_config(pattern: str, lang: str) -> Dict[str, Any]:
    # TODO remove when using sgrep -e ... -l ... instead of this hacked config
    return {
        "manual": {
            RULES_KEY: [
                {
                    ID_KEY: "-",
                    "pattern": pattern,
                    "message": pattern,
                    "languages": [lang],
                    "severity": "ERROR",
                }
            ]
        }
    }


def resolve_targets(targets: List[str]) -> List[Path]:
    base_path = get_base_path()
    return [
        Path(target) if Path(target).is_absolute() else base_path.joinpath(target)
        for target in targets
    ]


def adjust_for_docker(in_precommit: bool = False) -> None:
    # change into this folder so that all paths are relative to it
    if IN_DOCKER and not IN_GH_ACTION and not in_precommit:
        if not Path(REPO_HOME_DOCKER).exists():
            print_error_exit(
                f'you are running sgrep in docker, but you forgot to mount the current directory in Docker: missing: -v "${{PWD}}:{REPO_HOME_DOCKER}"'
            )
    if Path(REPO_HOME_DOCKER).exists():
        os.chdir(REPO_HOME_DOCKER)


def get_base_path() -> Path:
    return Path(".")


def indent(msg: str) -> str:
    return "\n".join(["\t" + line for line in msg.splitlines()])


def parse_config_at_path(
    loc: Path, base_path: Optional[Path] = None
) -> Dict[str, Optional[Dict[str, Any]]]:
    config_id = str(loc)
    if base_path:
        config_id = str(loc).replace(str(base_path), "")
    try:
        with loc.open() as f:
            return parse_config_string(config_id, f.read())
    except FileNotFoundError:
        print_error(f"YAML file at {loc} not found")
        return {str(loc): None}


def parse_config_string(
    config_id: str, contents: str
) -> Dict[str, Optional[Dict[str, Any]]]:
    try:
        return {config_id: yaml.safe_load(contents)}
    except yaml.parser.ParserError as se:
        print_error(f"Invalid yaml file {config_id}:\n{indent(str(se))}")
        return {config_id: None}
    except yaml.scanner.ScannerError as se:
        print_error(f"Invalid yaml file {config_id}:\n{indent(str(se))}")
        return {config_id: None}


def parse_config_folder(
    loc: Path, relative: bool = False
) -> Dict[str, Optional[Dict[str, Any]]]:
    configs = {}
    for l in loc.rglob("*"):
        if not _is_hidden_config_dir(l) and l.suffix in YML_EXTENSIONS:
            configs.update(parse_config_at_path(l, loc if relative else None))
    return configs


def _is_hidden_config_dir(loc: Path) -> bool:
    """
    Want to keep rules/.sgrep.yml but not path/.github/foo.yml
    Also want to keep src/.sgrep/bad_pattern.yml
    """
    return any(
        part != "."
        and part != ".."
        and part.startswith(".")
        and DEFAULT_SGREP_CONFIG_NAME not in part
        for part in loc.parts[:-1]
    )


def load_config_from_local_path(
    location: Optional[str] = None,
) -> Dict[str, Optional[Dict[str, Any]]]:
    base_path = get_base_path()
    if location is None:
        default_file = base_path.joinpath(DEFAULT_CONFIG_FILE)
        default_folder = base_path.joinpath(DEFAULT_CONFIG_FOLDER)
        if default_file.exists():
            return parse_config_at_path(default_file)
        elif default_folder.exists():
            return parse_config_folder(default_folder, relative=True)
        else:
            return {str(default_file): None}
    else:
        loc = base_path.joinpath(location)
        if loc.exists():
            if loc.is_file():
                return parse_config_at_path(loc)
            elif loc.is_dir():
                return parse_config_folder(loc)
            else:
                print_error_exit(f"config location `{loc}` is not a file or folder!")
                assert False
        else:
            addendum = ""
            if IN_DOCKER:
                addendum = " (since you are running in docker, you cannot specify arbitary paths on the host; they must be mounted into the container)"
            print_error_exit(
                f"unable to find a config; path `{loc}` does not exist{addendum}"
            )
            assert False


def download_config(config_url: str) -> Dict[str, Optional[Dict[str, Any]]]:
    debug_print(f"trying to download from {config_url}")
    try:
        r = requests.get(config_url, stream=True)
        if r.status_code == requests.codes.ok:
            content_type = r.headers.get("Content-Type")
            if content_type and "text/plain" in content_type:
                return parse_config_string("remote-url", r.content.decode("utf-8"))
            elif content_type and content_type == "application/x-gzip":
                fname = f"/tmp/{base64.b64encode(config_url.encode()).decode()}"
                shutil.rmtree(fname, ignore_errors=True)
                with tarfile.open(fileobj=r.raw, mode="r:gz") as tar:
                    tar.extractall(fname)
                extracted = Path(fname)
                for path in extracted.iterdir():
                    # get first folder in extracted folder (this is how GH does it)
                    return parse_config_folder(path, relative=True)
            else:
                print_error_exit(
                    f"unknown content-type: {content_type} returned by config url: {config_url}. Can not parse"
                )
                assert False
        else:
            print_error_exit(
                f"bad status code: {r.status_code} returned by config url: {config_url}"
            )
            assert False
    except Exception as e:
        print_error(str(e))
    return {config_url: None}


def resolve_config(config_str: Optional[str]) -> Dict[str, Optional[Dict[str, Any]]]:
    """ resolves if config arg is a registry entry, a url, or a file, folder, or loads from defaults if None"""
    start_t = time.time()
    if config_str is None:
        config = load_config_from_local_path()
    elif config_str in RULES_REGISTRY:
        config = download_config(RULES_REGISTRY[config_str])
    elif is_url(config_str):
        config = download_config(config_str)
    else:
        config = load_config_from_local_path(config_str)
    if config:
        debug_print(f"loaded {len(config)} configs in {time.time() - start_t}")
    return config


def generate_config() -> None:
    # defensive coding
    if Path(DEFAULT_CONFIG_FILE).exists():
        print_error_exit(
            f"{DEFAULT_CONFIG_FILE} already exists. Please remove and try again"
        )
    try:
        r = requests.get(TEMPLATE_YAML_URL, timeout=10)
        r.raise_for_status()
        template_str = r.text
    except Exception as e:
        debug_print(str(e))
        print_msg(
            f"There was a problem downloading the latest template config. Using fallback template"
        )
        template_str = """rules:
  - id: eqeq-is-bad
    pattern: $X == $X
    message: "$X == $X is a useless equality check"
    languages: [python]
    severity: ERROR"""
    try:
        with open(DEFAULT_CONFIG_FILE, "w") as template:
            template.write(template_str)
            print_msg(f"Template config successfully written to {DEFAULT_CONFIG_FILE}")
            sys.exit(0)
    except Exception as e:
        print_error_exit(str(e))
