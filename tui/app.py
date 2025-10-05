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

    def _get_key(self) -> Optional[str]:
        """
        Получение нажатой клавиши кроссплатформенно

        Returns:
            Строка с названием клавиши или None
        """
        try:
            if sys.platform == 'win32':
                # Windows
                import msvcrt
                if msvcrt.kbhit():
                    key = msvcrt.getch()

                    # Обработка специальных клавиш
                    if key == b'\xe0' or key == b'\x00':  # Расширенные клавиши
                        key = msvcrt.getch()
                        key_map = {
                            b'H': 'up',
                            b'P': 'down',
                            b'K': 'left',
                            b'M': 'right',
                        }
                        return key_map.get(key)
                    elif key == b'\x1b':  # ESC
                        return 'escape'
                    elif key == b'\r':  # Enter
                        return 'enter'
                    elif key == b' ':  # Space
                        return ' '
                    elif key == b'\x08':  # Backspace
                        return 'backspace'
                    else:
                        try:
                            return key.decode('utf-8', errors='ignore')
                        except:
                            return None
            else:
                # Linux/Unix
                import select
                import tty
                import termios

                if select.select([sys.stdin], [], [], 0.0)[0]:
                    # Сохраняем текущие настройки терминала
                    old_settings = termios.tcgetattr(sys.stdin)
                    try:
                        tty.setraw(sys.stdin.fileno())
                        ch = sys.stdin.read(1)

                        # Обработка escape-последовательностей
                        if ch == '\x1b':
                            # Читаем следующие символы для определения клавиши
                            ch2 = sys.stdin.read(1)
                            if ch2 == '[':
                                ch3 = sys.stdin.read(1)
                                key_map = {
                                    'A': 'up',
                                    'B': 'down',
                                    'C': 'right',
                                    'D': 'left',
                                }
                                return key_map.get(ch3, 'escape')
                            return 'escape'
                        elif ch == '\r' or ch == '\n':
                            return 'enter'
                        elif ch == ' ':
                            return ' '
                        elif ch == '\x7f':  # Backspace/Delete
                            return 'backspace'
                        else:
                            return ch
                    finally:
                        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)

        except Exception as e:
            logger.debug(f"Ошибка получения клавиши: {e}")
            return None

        return None

    def run(self):
        """Запуск TUI приложения"""
        self.running = True

        # Настраиваем логирование для TUI
        logger.remove()
        log_path = Path("data/logs/tui.log")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        logger.add(
            log_path,
            rotation="1 day",
            retention="7 days",
            level=self.config.get('log_level', 'INFO')
        )

        # Добавляем вывод логов в консоль
        # Они будут видны ПОД TUI интерфейсом
        logger.add(
            sys.stdout,
            format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
            level="INFO",
            colorize=True
        )

        logger.info("🚀 Запуск TUI приложения")

        try:
            # ИСПРАВЛЕНИЕ: используем screen=True для альтернативного экрана
            # Это позволит логам идти в основной буфер консоли
            with Live(
                    self.screens[self.current_screen_name].render(),
                    console=self.console,
                    refresh_per_second=4,
                    screen=True  # ВАЖНО: используем альтернативный экран!
            ) as live:

                while self.running:
                    # Получаем клавишу
                    key = self._get_key()

                    if key:
                        # Обрабатываем клавишу
                        current_screen = self.screens[self.current_screen_name]
                        result = current_screen.handle_key(key)

                        # Обновляем экран
                        try:
                            live.update(current_screen.render())
                        except Exception as e:
                            logger.error(f"Ошибка отрисовки экрана: {e}")

                        # Проверяем выход из приложения
                        if result is False and key.lower() == 'q' and self.current_screen_name == 'main':
                            self.running = False
                            logger.info("Выход из приложения по запросу пользователя")
                            break

                    # Небольшая задержка для снижения нагрузки на CPU
                    time.sleep(0.05)

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