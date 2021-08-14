from abc import ABCMeta, abstractmethod
from argparse import ArgumentParser
import logging
from pathlib import Path
import sys
from typing import NoReturn

from hephaistos import backups, config, hashes, helpers, lua_mod, patchers
from hephaistos import helpers
from hephaistos.config import LOGGER
from hephaistos.helpers import HadesNotFound, InteractiveModeCancelled, Scaling


class ParserBase(ArgumentParser):
    """Base parser for hosting shared behavior.

    - Print help when user supplies invalid arguments.
    - Shared arguments (verbosity, etc.).

    `ParserBase` serves as the base class for both the main CLI and the actual subcommand parsers,
    even if not defined as such (`BaseSubcommand` and children inherit from `ArgumentParser`).
    
    Counter-intuitively, the defined subcommand parsers must NOT directly inherit from `ParserBase`.
    This is due to how subparsers and parenting work in `argparse`:
    - When initializing subparsers via `add_subparsers`:
        - `parser_class` is provided as the base class to use for subcommand parsers.
    - When adding subparsers via `add_parser`:
        - A new instance of `parser_class` is instantiated.
        - If `parents` are provided, the parents' arguments are copied into the `parser_class` instance.
        - This new `parser_class` instance is the actual parser used for the subcommand.
    
    This means the actual type of the subparser is ignored, and must NOT be the same as
    `parser_class` to avoid argument conflicts while copying. This explains why only the main
    Hephaistos CLI is declared as deriving from `ParserBase`, even though at runtime all parsers
    (including `BaseSubcommand`) will inherit from `ParserBase`.
    """
    VERBOSE_TO_LOG_LEVEL = {
        0: logging.WARNING,
        1: logging.INFO,
        2: logging.DEBUG,
    }

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.add_argument('-v', '--verbose', action='count', default=0,
            help="verbosity level (none: errors only, '-v': info, '-vv': debug)")
        self.add_argument('--hades-dir', default='.',
            help="path to Hades directory (default: '.', i.e. current directory)")

    def error(self, message) -> NoReturn:
        """Print help when user supplies invalid arguments."""
        sys.stderr.write(f"error: {message}\n\n")
        self.print_help()
        sys.exit(2)


class Hephaistos(ParserBase):
    """Hephaistos entry point. Main parser for hosting the individual subcommands."""
    interactive_mode = False

    def __init__(self, **kwargs) -> None:
        super().__init__(prog=config.HEPHAISTOS_NAME, description="Hephaistos CLI", **kwargs)
        subparsers = self.add_subparsers(parser_class=ParserBase,
            help="one of:", metavar='subcommand', dest='subcommand')
        subcommands = {
            'patch': PatchSubcommand(),
            'restore': RestoreSubcommand(),
        }
        for name, subcommand in subcommands.items():
            subparsers.add_parser(name, parents=[subcommand],
                description=subcommand.description, help=subcommand.description)

        raw_args = sys.argv[1:]
        # if no argument is provided, enter interactive mode to help the user out
        if len(raw_args) == 0:
            self.interactive_mode = True
            self.__configure_hades_dir('.')
            try:
                self.__interactive(raw_args)
            except InteractiveModeCancelled:
                self.__exit()

        args = self.parse_args(raw_args)
        # handle global args
        self.__configure_logging(args.verbose)
        self.__configure_hades_dir(args.hades_dir)
        try:
            # handle subcommand args via SubcommandBase.dispatch handler
            args.dispatch(**vars(args))
        except Exception as e:
            LOGGER.exception(e) # log any unhandled exception
        self.__exit()

    def __interactive(self, raw_args: list[str]):
        msg = """Hi! This interactive wizard will help you to set up Hephaistos.
Note: while Hephaistos can be used in interactive mode for basic usage, you will need to switch to non-interactive mode for any advanced usage. See the README for more details.
"""
        print(msg)
        subcommand = helpers.interactive_pick(
            patch="Patch Hades using Hephaistos",
            restore="Restore Hades to its pre-Hephaistos state"
        )
        raw_args.append(subcommand)
        if subcommand == 'patch':
            (width, height) = helpers.interactive_pick(
                options=[
                    '2560 x 1080',
                    '3440 x 1440',
                    '3840 x 1600',
                    '5120 x 2160',
                    '3840 x 1080',
                    '5120 x 1440',
                ]
            ).split(' x ')
            raw_args.append(width)
            raw_args.append(height)
        raw_args.append('-v') # auto-enable verbose mode

    def __configure_logging(self, verbose_arg: int):
        level = ParserBase.VERBOSE_TO_LOG_LEVEL[min(verbose_arg, 2)]
        LOGGER.setLevel(level)

    def __configure_hades_dir(self, hades_dir_arg: str):
        config.hades_dir = Path(hades_dir_arg)
        try:
            helpers.is_valid_hades_dir(config.hades_dir)
        except HadesNotFound as e:
            LOGGER.error(e)
            hades_dirs = helpers.try_detect_hades_dirs()
            if len(hades_dirs) > 0:
                advice = '\n'.join(f"  - {hades_dir}" for hades_dir in hades_dirs)
            else:
                advice = "  - Could not auto-detect any Hades directory."
            msg = f"""Hephaistos does not seem to be located in the Hades directory:
{advice}
Please move Hephaistos directly to the Hades directory.
If you know what you're doing, you can also re-run with '--hades-dir' to manually specify Hades directory while storing Hephaistos elsewhere."""
            LOGGER.error(msg)
            self.__exit(1)

    def __exit(self, status_code=None):
        # if we were in interactive mode, assume user simply double-clicked on
        # the binary instead of launching from the command line
        if self.interactive_mode:
            input("Press enter to exit...")
        sys.exit(status_code)


class BaseSubcommand(ArgumentParser, metaclass=ABCMeta):
    def __init__(self, description: str, **kwargs) -> None:
        super().__init__(add_help=False, **kwargs)
        self.description = description
        self.set_defaults(dispatch=self.handler)

    @abstractmethod
    def handler(self, **kwargs) -> None:
        raise NotImplementedError("Subclasses must implement a handler method.")


class PatchSubcommand(BaseSubcommand):
    def __init__(self, **kwargs) -> None:
        super().__init__(description="patch Hades based on given display resolution", **kwargs)
        self.add_argument('width', type=int, help="display resolution width")
        self.add_argument('height', type=int, help="display resolution height")
        self.add_argument('-s', '--scaling', default=Scaling.HOR_PLUS,
            choices=[Scaling.HOR_PLUS.value, Scaling.PIXEL_BASED.value],
            help="scaling type (default: hor+)")
        self.add_argument('-f', '--force', action='store_true',
            help="force patching, bypassing hash check and removing previous backups (useful after game update)")

    def handler(self, width: int, height: int, scaling: Scaling, force: bool, **kwargs) -> None:
        """Compute viewport depending on arguments, then patch all needed files and install Lua mod.
        If using '--force', invalidate backups and hashes."""
        config.new_viewport = helpers.compute_viewport(width, height, scaling)
        LOGGER.info(f"Computed patch viewport {config.new_viewport} using scaling {scaling} from resolution ({width}, {height})")

        if force:
            backups.invalidate()
            hashes.invalidate()

        try:
            patchers.patch_engines()
            patchers.patch_sjsons()
            lua_mod.install()
        except hashes.HashMismatch as e:
            LOGGER.error(e)
            LOGGER.error("Was the game updated? Re-run with '--force' to invalidate previous backups and re-patch Hades from its current state.")
        except (LookupError, FileExistsError) as e:
            LOGGER.error(e)


class RestoreSubcommand(BaseSubcommand):
    def __init__(self, **kwargs) -> None:
        super().__init__(description="restore Hades to its pre-Hephaistos state", **kwargs)

    def handler(self, **kwargs) -> None:
        """Restore all backups, invalidate all hashes, uninstall Lua mod."""
        backups.restore()
        hashes.invalidate()
        lua_mod.uninstall()
