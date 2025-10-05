"""
Главное приложение TUI
"""

import sys
import time
from pathlib import Path
from typing import Dict, Optional
import yaml
from rich.console import Console
from rich.live import Live
from loguru import logger

from tui.base_screen import BaseScreen
from tui.main_screen import MainScreen
from tui.emulators_screen import EmulatorsScreen
from tui.settings_screen import SettingsScreen
from tui.status_screen import StatusScreen
from orchestrator import get_orchestrator


class BotTUIApp:
    """Главное приложение TUI"""

    def __init__(self):
        """Инициализация приложения"""
        self.console = Console()
        self.orchestrator = get_orchestrator()

        # Загрузка конфигурации
        self.config_path = Path("configs/tui_config.yaml")
        self.config = self._load_config()

        # Инициализация экранов
        self.screens: Dict[str, BaseScreen] = {
            'main': MainScreen(self),
            'emulators': EmulatorsScreen(self),
            'settings': SettingsScreen(self),
            'status': StatusScreen(self),
        }

        self.current_screen_name = 'main'
        self.running = False

    def _load_config(self) -> Dict:
        """Загрузка конфигурации TUI"""
        default_config = {
            'max_concurrent_emulators': 5,
            'theme': 'default',
            'log_level': 'INFO',
            'auto_refresh_interval': 5
        }

        if self.config_path.exists():
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f)
                    # Объединяем с дефолтами
                    return {**default_config, **config.get('tui', {})}
            except Exception as e:
                logger.warning(f"Ошибка загрузки конфигурации TUI: {e}")
                return default_config
        else:
            # Создаем дефолтный конфиг
            self._save_default_config(default_config)
            return default_config

    def _save_default_config(self, config: Dict):
        """Создание дефолтной конфигурации"""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                yaml.dump({'tui': config}, f, allow_unicode=True)
            logger.info(f"Создана дефолтная конфигурация TUI: {self.config_path}")
        except Exception as e:
            logger.error(f"Ошибка создания конфигурации: {e}")

    def save_config(self):
        """Сохранение конфигурации"""
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                yaml.dump({'tui': self.config}, f, allow_unicode=True)
            logger.info("Конфигурация TUI сохранена")
        except Exception as e:
            logger.error(f"Ошибка сохранения конфигурации: {e}")

    def switch_screen(self, screen_name: str):
        """
        Переключение на другой экран

        Args:
            screen_name: Имя экрана для переключения
        """
        if screen_name in self.screens:
            # Деактивируем текущий экран
            self.screens[self.current_screen_name].deactivate()

            # Активируем новый экран
            self.current_screen_name = screen_name
            self.screens[screen_name].activate()

            logger.debug(f"Переключились на экран: {screen_name}")

    def run(self):
        """Запуск TUI приложения"""
        self.running = True

        # Настраиваем логирование для TUI
        # Убираем вывод логов в консоль, оставляем только в файл
        logger.remove()
        log_path = Path("data/logs/tui.log")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        logger.add(
            log_path,
            rotation="1 day",
            retention="7 days",
            level=self.config.get('log_level', 'INFO')
        )

        # Добавляем минимальный вывод в консоль ниже TUI
        logger.add(
            sys.stdout,
            format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
            level="INFO",
            colorize=True
        )

        logger.info("🚀 Запуск TUI приложения")

        try:
            with Live(
                    self.screens[self.current_screen_name].render(),
                    console=self.console,
                    refresh_per_second=4,
                    screen=False  # Не используем альтернативный экран для отображения логов ниже
            ) as live:

                while self.running:
                    # Получаем ввод без блокировки
                    if self.console.is_terminal:
                        # Обновляем отображение
                        try:
                            current_screen = self.screens[self.current_screen_name]
                            live.update(current_screen.render())
                        except Exception as e:
                            logger.error(f"Ошибка отрисовки экрана: {e}")

                        # Читаем клавишу с таймаутом
                        try:
                            import msvcrt
                            if msvcrt.kbhit():
                                key = msvcrt.getch().decode('utf-8', errors='ignore')

                                # Обработка специальных клавиш
                                if key == '\xe0':  # Расширенные клавиши
                                    key = msvcrt.getch().decode('utf-8', errors='ignore')
                                    if key == 'H':
                                        key = 'up'
                                    elif key == 'P':
                                        key = 'down'
                                elif key == '\x1b':  # ESC
                                    key = 'escape'
                                elif key == '\r':  # Enter
                                    key = 'enter'
                                elif key == ' ':  # Space
                                    key = ' '
                                elif key == '\x08':  # Backspace
                                    key = 'backspace'

                                # Обрабатываем клавишу
                                result = current_screen.handle_key(key)
                                if result is False and key.lower() == 'q' and self.current_screen_name == 'main':
                                    self.running = False
                                    logger.info("Выход из приложения по запросу пользователя")
                                    break
                        except ImportError:
                            # Unix-системы - используем другой подход
                            import select
                            if select.select([sys.stdin], [], [], 0.1)[0]:
                                key = sys.stdin.read(1)
                                current_screen.handle_key(key)

                    time.sleep(0.1)

        except KeyboardInterrupt:
            logger.info("Получен сигнал прерывания (Ctrl+C)")
        except Exception as e:
            logger.error(f"Критическая ошибка TUI: {e}")
            import traceback
            logger.error(traceback.format_exc())
        finally:
            # Останавливаем обработку при выходе
            if self.orchestrator.get_processing_status().get('processor_running'):
                logger.info("Останавливаем обработку перед выходом...")
                self.orchestrator.stop_processing()

            self.running = False
            logger.info("TUI приложение завершено")