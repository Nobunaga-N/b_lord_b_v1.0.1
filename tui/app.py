"""
Главное приложение TUI с встроенной панелью логов
"""

import sys
import time
from pathlib import Path
from typing import Dict, Optional, List
from collections import deque
from datetime import datetime
import yaml
from rich.console import Console
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel
from rich.text import Text
from loguru import logger

from tui.base_screen import BaseScreen
from tui.main_screen import MainScreen
from tui.emulators_screen import EmulatorsScreen
from tui.settings_screen import SettingsScreen
from tui.status_screen import StatusScreen
from orchestrator import get_orchestrator


class LogBuffer:
    """Буфер для хранения последних логов"""

    def __init__(self, max_lines: int = 15):
        self.max_lines = max_lines
        self.logs = deque(maxlen=max_lines)

    def add(self, message: str, level: str = "INFO"):
        """Добавить лог в буфер"""
        timestamp = datetime.now().strftime("%H:%M:%S")

        # Определяем цвет по уровню
        color_map = {
            "DEBUG": "dim",
            "INFO": "white",
            "SUCCESS": "green",
            "WARNING": "yellow",
            "ERROR": "red",
            "CRITICAL": "bold red"
        }
        color = color_map.get(level, "white")

        self.logs.append({
            'timestamp': timestamp,
            'level': level,
            'message': message,
            'color': color
        })

    def get_logs_panel(self) -> Panel:
        """Получить панель с логами для отображения"""
        if not self.logs:
            content = Text("Логи появятся здесь...", style="dim")
        else:
            content = Text()
            for log in self.logs:
                # Форматируем лог
                content.append(f"[{log['timestamp']}] ", style="cyan")
                content.append(f"{log['level']:<8} ", style=log['color'])
                content.append(f"| {log['message']}\n", style=log['color'])

        return Panel(
            content,
            title="[cyan]📋 Логи[/cyan]",
            border_style="cyan",
            height=10  # Фиксированная высота панели логов
        )


class BotTUIApp:
    """Главное приложение TUI с панелью логов"""

    def __init__(self):
        """Инициализация приложения"""
        self.console = Console()
        self.orchestrator = get_orchestrator()

        # Буфер логов
        self.log_buffer = LogBuffer(max_lines=15)

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
                    return {**default_config, **config.get('tui', {})}
            except Exception as e:
                logger.warning(f"Ошибка загрузки конфигурации TUI: {e}")
                return default_config
        else:
            self._save_default_config()
            return default_config

    def _save_default_config(self):
        """Сохранение конфига по умолчанию"""
        default_config = {
            'tui': {
                'max_concurrent_emulators': 5,
                'theme': 'default',
                'log_level': 'INFO',
                'auto_refresh_interval': 5
            }
        }

        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, 'w', encoding='utf-8') as f:
            yaml.dump(default_config, f, allow_unicode=True)

    def save_config(self):
        """Сохранение текущей конфигурации"""
        try:
            config_data = {
                'tui': self.config
            }
            with open(self.config_path, 'w', encoding='utf-8') as f:
                yaml.dump(config_data, f, allow_unicode=True)
            return True
        except Exception as e:
            logger.error(f"Ошибка сохранения конфигурации: {e}")
            return False

    def switch_screen(self, screen_name: str):
        """Переключение между экранами"""
        if screen_name in self.screens:
            # Деактивируем текущий экран
            self.screens[self.current_screen_name].deactivate()

            # Переключаемся
            self.current_screen_name = screen_name

            # Активируем новый экран
            self.screens[screen_name].activate()

            self.log_buffer.add(f"Переход на экран: {screen_name}", "DEBUG")

    def render_with_logs(self) -> Layout:
        """Рендер текущего экрана с панелью логов внизу"""
        main_layout = Layout()

        # Получаем рендер текущего экрана
        screen_layout = self.screens[self.current_screen_name].render()

        # Создаем панель логов
        logs_panel = self.log_buffer.get_logs_panel()

        # Компонуем: экран сверху (80%), логи снизу (20%)
        main_layout.split_column(
            Layout(screen_layout, ratio=4),
            Layout(logs_panel, size=10)
        )

        return main_layout

    def _get_key(self) -> Optional[str]:
        """Получение нажатой клавиши (неблокирующее чтение)"""
        import select

        if sys.platform == 'win32':
            import msvcrt
            if msvcrt.kbhit():
                ch = msvcrt.getch()
                if ch in (b'\x00', b'\xe0'):
                    ch2 = msvcrt.getch()
                    arrow_map = {b'H': 'up', b'P': 'down', b'K': 'left', b'M': 'right'}
                    return arrow_map.get(ch2, None)
                try:
                    key = ch.decode('utf-8')
                    if key == '\r':
                        return 'enter'
                    elif key == '\x1b':
                        return 'escape'
                    elif key == '\x08':
                        return 'backspace'
                    return key
                except:
                    return None
            return None
        else:
            import termios
            import tty

            if not select.select([sys.stdin], [], [], 0)[0]:
                return None

            try:
                old_settings = termios.tcgetattr(sys.stdin)
                try:
                    tty.setraw(sys.stdin.fileno())
                    ch = sys.stdin.read(1)

                    if ch == '\x1b':
                        ch2 = sys.stdin.read(1)
                        if ch2 == '[':
                            ch3 = sys.stdin.read(1)
                            key_map = {'A': 'up', 'B': 'down', 'C': 'right', 'D': 'left'}
                            return key_map.get(ch3, 'escape')
                        return 'escape'
                    elif ch == '\r' or ch == '\n':
                        return 'enter'
                    elif ch == ' ':
                        return ' '
                    elif ch == '\x7f':
                        return 'backspace'
                    else:
                        return ch
                finally:
                    termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
            except Exception as e:
                logger.debug(f"Ошибка получения клавиши: {e}")
                return None

        return None

    def _setup_logging(self):
        """Настройка системы логирования с перехватом для TUI"""
        # Удаляем все существующие обработчики
        logger.remove()

        # Добавляем запись в файл
        log_path = Path("data/logs/tui.log")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        logger.add(
            log_path,
            rotation="1 day",
            retention="7 days",
            level=self.config.get('log_level', 'INFO'),
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {message}"
        )

        # Добавляем кастомный обработчик для TUI буфера
        def tui_sink(message):
            """Кастомный sink для перехвата логов в TUI буфер"""
            record = message.record
            level = record["level"].name
            msg = record["message"]
            self.log_buffer.add(msg, level)

        logger.add(
            tui_sink,
            level="INFO",
            format="{message}"
        )

        self.log_buffer.add("🚀 Система логирования TUI инициализирована", "SUCCESS")

    def run(self):
        """Запуск TUI приложения"""
        self.running = True

        # Настраиваем логирование
        self._setup_logging()

        logger.info("=" * 60)
        logger.info("Beast Lord Bot - TUI Interface v2.1")
        logger.info("=" * 60)

        try:
            with Live(
                self.render_with_logs(),
                console=self.console,
                refresh_per_second=4,
                screen=True
            ) as live:

                while self.running:
                    # Получаем клавишу
                    key = self._get_key()

                    if key:
                        # Обрабатываем клавишу
                        current_screen = self.screens[self.current_screen_name]
                        result = current_screen.handle_key(key)

                        # Обновляем экран с логами
                        try:
                            live.update(self.render_with_logs())
                        except Exception as e:
                            logger.error(f"Ошибка отрисовки экрана: {e}")

                        # Проверяем выход из приложения
                        if result is False and key.lower() == 'q' and self.current_screen_name == 'main':
                            self.running = False
                            logger.info("Выход из приложения по запросу пользователя")
                            break

                    # Автообновление экрана каждые N секунд
                    # (для отображения новых логов даже без нажатия клавиш)
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