"""
Базовый класс для всех экранов TUI
"""

from abc import ABC, abstractmethod
from rich.console import Console
from rich.layout import Layout


class BaseScreen(ABC):
    """Базовый класс для экранов TUI"""

    def __init__(self, app):
        """
        Инициализация экрана

        Args:
            app: Экземпляр BotTUIApp
        """
        self.app = app
        self.console = Console()

    @abstractmethod
    def render(self) -> Layout:
        """
        Отрисовка экрана

        Returns:
            Layout для отображения
        """
        pass

    @abstractmethod
    def handle_key(self, key: str) -> bool:
        """
        Обработка нажатия клавиши

        Args:
            key: Нажатая клавиша

        Returns:
            True если нужно перерисовать экран
        """
        pass

    def activate(self):
        """Вызывается при активации экрана"""
        pass

    def deactivate(self):
        """Вызывается при деактивации экрана"""
        pass