from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress


def get_display():
    """Get an instance of the MarvinDisplay class."""
    return MarvinDisplay()


class MarvinDisplay:
    """A class to handle display messages in the console."""

    def __init__(self):
        """Initialize the MarvinDisplay class."""
        self.console = Console()
        self.progress = Progress(
            *Progress.get_default_columns(),
            console=self.console,
            expand=True,
            transient=True,
        )

    def header(self, title: str, subtitle: str | None = None):
        """Print a header message in the console."""
        self.console.print(Panel(f"[bold magenta]{title}[/bold magenta]\n{subtitle}", expand=False))

    def section(self, title: str, subtitle: str | None = None):
        """Print a section message in the console."""
        self.console.print(f"[bold blue]{title}[/bold blue]")
        if subtitle:
            self.console.print(f"[dim]{subtitle}[/dim]")

    def step(self, step: str, title: str, total_steps: int | None = None, subtitle: str | None = None):
        """Print a step message in the console."""
        self.console.print(f"[bold green]Step {step}/{total_steps}: {title}[/bold green]")
        if subtitle:
            self.console.print(f"[dim]{subtitle}[/dim]")

    def info(self, message: str):
        """Print an info message in the console."""
        self.console.print(f"[bold blue]{message}[/bold blue]")

    def success(self, message: str):
        """Print a success message in the console."""
        self.console.print(f"[bold green]{message}[/bold green]")

    def warning(self, message: str):
        """Print a warning message in the console."""
        self.console.print(f"[bold yellow]{message}[/bold yellow]")

    def error(self, message: str):
        """Print an error message in the console."""
        self.console.print(f"[bold red]{message}[/bold red]")

    def spinner(self, message: str):
        """Start a spinner with a message.

        Args:
            message (str): The message to display with the spinner.
        """
        self.console.print(f"[dim]{message}...[/dim]")
        return self.progress.add_task(message)

    def prompt(self, message: str, choices: list[Any] | None = None, default: str | None = None):
        """Display an interactive prompt.

        Args:
            message (str): The message to display in the prompt.
            choices (list, optional): A list of choices for the prompt. Defaults to None.
            default (str, optional): The default value for the prompt. Defaults to None.
        """
        prompt = f"{message}"
        if choices:
            prompt += f" ({'/'.join(choices)})"
        if default:
            prompt += f" [default: {default}]"
        self.console.print(f"[bold blue]{message}[/bold blue]")
        return self.console.input(f"{message}: ")
