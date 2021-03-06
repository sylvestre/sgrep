#!/usr/bin/env python3
import argparse
import test

import config_resolver
import sgrep_main
import util
from constants import DEFAULT_CONFIG_FILE
from constants import PLEASE_FILE_ISSUE_TEXT
from constants import RCE_RULE_FLAG
from constants import SGREP_URL
from util import debug_print
from util import print_error_exit

# CLI


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=f"sgrep CLI. For more information about sgrep, go to {SGREP_URL}",
        prog="sgrep",  # we have to lie to the user since they know of this as `sgrep`
    )

    # input
    parser.add_argument(
        "target",
        nargs="*",
        default=["."],
        help="Files to search (by default, entire current working directory searched). Implied argument if piping to sgrep.",
    )

    # config options
    config = parser.add_argument_group("config")
    config_ex = config.add_mutually_exclusive_group()
    config_ex.add_argument(
        "-g",
        "--generate-config",
        help=f"Generte starter {DEFAULT_CONFIG_FILE}",
        action="store_true",
    )

    config_ex.add_argument(
        "-f",
        "--config",
        help=f"Config YAML file or directory of YAML files ending in .yml|.yaml, OR URL of a config file, OR sgrep registry entry name. See the README for sgrep for information on config file format.",
    )

    config_ex.add_argument("-e", "--pattern", help="sgrep pattern")
    config.add_argument(
        "-l",
        "--lang",
        help="Parses pattern and all files in specified language. Must be used with -e/--pattern.",
    )
    config.add_argument(
        "--validate",
        help=f"Validate config file(s). No search is performed.",
        action="store_true",
    )
    config.add_argument(
        "--strict",
        help=f"only invoke sgrep if config(s) are valid",
        action="store_true",
    )

    config.add_argument(
        RCE_RULE_FLAG,
        help=f"DANGEROUS: allow rules to run arbitrary code: ONLY ENABLE IF YOU TRUST THE SOURCE OF ALL RULES IN YOUR CONFIG.",
        action="store_true",
    )

    config.add_argument(
        "--exclude-tests",
        help=f"try to exclude tests, documentation, and examples (based on filename/path)",
        action="store_true",
    )
    config.add_argument("--precommit", help=argparse.SUPPRESS, action="store_true")

    # output options
    output = parser.add_argument_group("output")

    output.add_argument(
        "-q",
        "--quiet",
        help="Do not print anything to stdout. Search results can still be saved to an output file specified by -o/--output. Exit code provides success status.",
        action="store_true",
    )

    output.add_argument(
        "--no-rewrite-rule-ids",
        help="Do not rewrite rule ids when they appear in nested subfolders (by default, rule 'foo' in test/rules.yaml will be renamed 'test.foo')",
        action="store_true",
    )

    output.add_argument(
        "-o",
        "--output",
        help="Save search results to a file or post to URL. Default is to print to stdout.",
    )
    output.add_argument(
        "--json", help="Convert search output to JSON format.", action="store_true"
    )
    output.add_argument("--test", help="Run a test suite", action="store_true")
    parser.add_argument(
        "--test-ignore-todo",
        help="Ignore rules marked as #todoruleid: in test files",
        action="store_true",
    )
    output.add_argument(
        "--r2c",
        help="output json in r2c platform format (https://app.r2c.dev)",
        action="store_true",
    )
    output.add_argument(
        "--skip-pattern-validation",
        help="skip using sgrep to validate patterns before running (not recommended)",
        action="store_true",
    )
    output.add_argument(
        "--dump-ast",
        help="show AST of the input file or passed expression and then exit (can use --json)",
        action="store_true",
    )
    output.add_argument(
        "--error",
        help="System Exit 1 if there are findings. Useful for CI and scripts.",
        action="store_true",
    )
    # logging options
    logging = parser.add_argument_group("logging")

    logging.add_argument(
        "-v",
        "--verbose",
        help=f"Sets the logging level to verbose. E.g. statements about which files are being processed will be printed.",
        action="store_true",
    )

    ### Parse and validate
    args = parser.parse_args()
    if args.pattern and not args.lang:
        parser.error("-e/--pattern and -l/--lang must both be specified")

    # set the flags
    util.set_flags(args.verbose, args.quiet)

    # change cwd if using docker
    config_resolver.adjust_for_docker(args.precommit)

    try:
        if args.test:
            test.test_main(args)
        else:
            sgrep_main.main(args)
    except NotImplementedError as ex:
        print_error_exit(
            f"sgrep encountered an error: {ex}; this is not your fault. {PLEASE_FILE_ISSUE_TEXT}"
        )
