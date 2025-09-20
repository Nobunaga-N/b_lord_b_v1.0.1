"""
Разумная интеграция с LDConsole для управления эмуляторами LDPlayer.
Обеспечивает простое управление жизненным циклом эмуляторов без излишней сложности.
"""

import time
import subprocess
from typing import Optional, Dict, Any
from pathlib import Path

from loguru import logger


class SmartLDConsole:
    """Класс для разумного управления эмуляторами через LDConsole"""

    def __init__(self, ldconsole_path: Optional[Path] = None):
        """
        Инициализация SmartLDConsole

        Args:
            ldconsole_path: Путь к ldconsole.exe (автоопределение если None)
        """
        self.ldconsole_path = ldconsole_path
        self._find_ldconsole_if_needed()

        logger.info(f"Инициализирован SmartLDConsole с путем: {self.ldconsole_path}")

    def _find_ldconsole_if_needed(self) -> None:
        """Поиск ldconsole.exe если путь не указан"""
        if self.ldconsole_path and self.ldconsole_path.exists():
            return

        logger.info("Ищем ldconsole.exe...")

        # Стандартные пути LDPlayer
        possible_paths = [
            Path("C:/LDPlayer/LDPlayer9/ldconsole.exe"),
            Path("C:/LDPlayer9/ldconsole.exe"),
            Path("D:/LDPlayer/LDPlayer9/ldconsole.exe"),
            Path("D:/LDPlayer9/ldconsole.exe"),
            Path("E:/LDPlayer/LDPlayer9/ldconsole.exe"),
            Path("E:/LDPlayer9/ldconsole.exe"),
            Path("C:/LDPlayer/LDPlayer4.0/ldconsole.exe"),
            Path("C:/LDPlayer4.0/ldconsole.exe"),
            Path("D:/LDPlayer/LDPlayer4.0/ldconsole.exe"),
            Path("D:/LDPlayer4.0/ldconsole.exe"),
            Path("E:/LDPlayer/LDPlayer4.0/ldconsole.exe"),
            Path("E:/LDPlayer4.0/ldconsole.exe"),
        ]

        for path in possible_paths:
            if path.exists():
                self.ldconsole_path = path
                logger.success(f"ldconsole.exe найден: {path}")
                return

        # Пробуем найти в PATH
        try:
            result = subprocess.run(
                ["where", "ldconsole.exe"],
                capture_output=True, text=True, shell=True
            )
            if result.returncode == 0:
                found_path = Path(result.stdout.strip().split('\n')[0])
                if found_path.exists():
                    self.ldconsole_path = found_path
                    logger.success(f"ldconsole.exe найден в PATH: {found_path}")
                    return
        except Exception:
            pass

        logger.error("ldconsole.exe не найден!")

    def _execute_ldconsole_command(self, command: str, timeout: float = 30.0) -> tuple[bool, str]:
        """
        Выполнение команды ldconsole с обработкой ошибок

        Args:
            command: Команда для выполнения (без ldconsole)
            timeout: Таймаут выполнения в секундах

        Returns:
            Кортеж (успех, вывод команды)
        """
        if not self.ldconsole_path or not self.ldconsole_path.exists():
            logger.error("ldconsole.exe не найден")
            return False, "ldconsole not found"

        try:
            full_command = [str(self.ldconsole_path)] + command.split()
            logger.debug(f"Выполняем команду: {' '.join(full_command)}")

            result = subprocess.run(
                full_command,
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding='utf-8',
                errors='ignore'
            )

            success = result.returncode == 0
            output = result.stdout if success else result.stderr

            if success:
                logger.debug(f"Команда выполнена успешно: {command}")
            else:
                logger.warning(f"Команда завершилась с ошибкой: {command}, код: {result.returncode}")
                logger.debug(f"Ошибка: {result.stderr}")

            return success, output

        except subprocess.TimeoutExpired:
            logger.error(f"Таймаут выполнения команды: {command}")
            return False, "timeout"
        except Exception as e:
            logger.error(f"Ошибка выполнения команды {command}: {e}")
            return False, str(e)

    def start_emulator(self, index: int, wait_ready: bool = True, timeout: float = 90.0) -> bool:
        """
        Запуск эмулятора по индексу

        Args:
            index: Индекс эмулятора
            wait_ready: Ожидать готовности ADB после запуска
            timeout: Таймаут запуска в секундах

        Returns:
            True если запуск успешен, False иначе
        """
        logger.info(f"Запускаем эмулятор {index}...")

        # Проверяем не запущен ли уже
        if self.is_running(index):
            logger.info(f"Эмулятор {index} уже запущен")
            return True

        # Запускаем эмулятор
        success, output = self._execute_ldconsole_command(f"launch --index {index}", timeout=30.0)

        if not success:
            logger.error(f"Не удалось запустить эмулятор {index}: {output}")
            return False

        logger.info(f"Команда запуска эмулятора {index} отправлена")

        # Ожидаем готовности если требуется
        if wait_ready:
            if self.wait_emulator_ready(index, timeout):
                logger.success(f"Эмулятор {index} запущен и готов к работе")
                return True
            else:
                logger.error(f"Эмулятор {index} запустился, но не готов к работе")
                return False
        else:
            logger.info(f"Эмулятор {index} запускается (без ожидания готовности)")
            return True

    def stop_emulator(self, index: int, force: bool = False) -> bool:
        """
        Остановка эмулятора по индексу

        Args:
            index: Индекс эмулятора
            force: Принудительная остановка

        Returns:
            True если остановка успешна, False иначе
        """
        logger.info(f"Останавливаем эмулятор {index} (force={force})...")

        # Проверяем не остановлен ли уже
        if not self.is_running(index):
            logger.info(f"Эмулятор {index} уже остановлен")
            return True

        # Выбираем команду остановки
        command = f"quit --index {index}"
        if force:
            command = f"quitall --index {index}"

        success, output = self._execute_ldconsole_command(command, timeout=20.0)

        if not success:
            logger.error(f"Не удалось остановить эмулятор {index}: {output}")
            return False

        # Даем время на корректную остановку
        logger.info(f"Ожидаем остановки эмулятора {index}...")
        max_wait = 15.0
        check_interval = 2.0
        elapsed = 0.0

        while elapsed < max_wait:
            time.sleep(check_interval)
            elapsed += check_interval

            if not self.is_running(index):
                logger.success(f"Эмулятор {index} успешно остановлен")
                return True

        logger.warning(f"Эмулятор {index} не остановился в течение {max_wait}с")
        return False

    def is_running(self, index: int) -> bool:
        """
        Проверка запущен ли эмулятор

        Args:
            index: Индекс эмулятора

        Returns:
            True если эмулятор запущен, False иначе
        """
        try:
            success, output = self._execute_ldconsole_command("list2", timeout=10.0)

            if not success:
                logger.warning(f"Не удалось получить список эмуляторов для проверки {index}")
                return False

            # Парсим вывод list2 для поиска запущенного эмулятора
            lines = output.strip().split('\n')
            for line in lines:
                line = line.strip()
                if not line:
                    continue

                try:
                    # Пробуем парсить JSON формат
                    import json
                    data = json.loads(line)
                    if (isinstance(data, dict) and
                            data.get("index") == index and
                            data.get("is_running", False)):
                        return True
                except json.JSONDecodeError:
                    # Пробуем парсить текстовый формат
                    # Формат: index,name,top_window_title,top_window_handle,is_running
                    parts = line.split(',')
                    if len(parts) >= 5:
                        try:
                            emu_index = int(parts[0])
                            is_running_str = parts[4].strip().lower()
                            is_running = is_running_str in ['true', '1', 'yes']
                            if emu_index == index and is_running:
                                return True
                        except (ValueError, IndexError):
                            continue

            return False

        except Exception as e:
            logger.error(f"Ошибка при проверке статуса эмулятора {index}: {e}")
            return False

    def wait_emulator_ready(self, index: int, timeout: float = 90.0) -> bool:
        """
        Ожидание готовности эмулятора для ADB подключения

        Args:
            index: Индекс эмулятора
            timeout: Максимальное время ожидания в секундах

        Returns:
            True если эмулятор готов, False иначе
        """
        logger.info(f"Ожидаем готовности эмулятора {index} (таймаут: {timeout}с)")

        start_time = time.time()
        check_interval = 10.0  # Проверка каждые 10 секунд

        while time.time() - start_time < timeout:
            # Проверяем что эмулятор запущен
            if not self.is_running(index):
                logger.warning(f"Эмулятор {index} больше не запущен")
                return False

            # Тестируем ADB подключение
            adb_port = self.get_adb_port(index)
            if self.test_adb_connection(adb_port):
                elapsed = time.time() - start_time
                logger.success(f"Эмулятор {index} готов к работе через {elapsed:.1f}с")
                return True

            # Показываем прогресс
            elapsed = time.time() - start_time
            logger.info(f"Эмулятор {index} еще не готов, прошло {elapsed:.1f}с...")

            # Ждем до следующей проверки
            time.sleep(check_interval)

        logger.error(f"Эмулятор {index} не готов после {timeout}с ожидания")
        return False

    def get_adb_port(self, index: int) -> int:
        """
        Получение ADB порта по стандартной формуле

        Args:
            index: Индекс эмулятора

        Returns:
            ADB порт эмулятора
        """
        # Стандартная формула пользователя: 5554 + index * 2
        port = 5554 + index * 2
        logger.debug(f"ADB порт для эмулятора {index}: {port}")
        return port

    def test_adb_connection(self, port: int) -> bool:
        """
        Быстрая проверка ADB подключения к порту

        Args:
            port: ADB порт для проверки

        Returns:
            True если подключение доступно, False иначе
        """
        try:
            # Метод 1: Проверяем через adb devices
            result = subprocess.run(
                ["adb", "devices"],
                capture_output=True,
                text=True,
                timeout=5.0
            )

            if result.returncode == 0:
                # Ищем устройство в формате emulator-XXXX
                emulator_name = f"emulator-{port}"
                for line in result.stdout.split('\n'):
                    if emulator_name in line and "device" in line:
                        logger.debug(f"Устройство {emulator_name} найдено в adb devices")

                        # Метод 2: Тестируем shell команду
                        try:
                            shell_result = subprocess.run(
                                ["adb", "-s", emulator_name, "shell", "echo", "test"],
                                capture_output=True,
                                text=True,
                                timeout=3.0
                            )

                            if shell_result.returncode == 0 and "test" in shell_result.stdout:
                                logger.debug(f"ADB порт {port} ({emulator_name}) работает корректно")
                                return True
                            else:
                                logger.debug(f"ADB {emulator_name} не отвечает на shell команды")
                                return False

                        except subprocess.TimeoutExpired:
                            logger.debug(f"Таймаут shell команды для {emulator_name}")
                            return False

            logger.debug(f"ADB порт {port} недоступен")
            return False

        except subprocess.TimeoutExpired:
            logger.debug(f"Таймаут при проверке ADB порта {port}")
            return False
        except FileNotFoundError:
            logger.warning("Команда adb не найдена в PATH")
            return False
        except Exception as e:
            logger.debug(f"Ошибка при проверке ADB порта {port}: {e}")
            return False

    def get_emulator_list(self) -> list[dict]:
        """
        Получение списка всех эмуляторов

        Returns:
            Список словарей с информацией об эмуляторах
        """
        logger.debug("Получаем список всех эмуляторов...")

        success, output = self._execute_ldconsole_command("list2", timeout=15.0)

        if not success:
            logger.error(f"Не удалось получить список эмуляторов: {output}")
            return []

        emulators = []
        lines = output.strip().split('\n')

        for line in lines:
            line = line.strip()
            if not line:
                continue

            try:
                # Пробуем парсить JSON формат
                import json
                data = json.loads(line)
                if isinstance(data, dict) and "index" in data:
                    emulator_info = {
                        "index": int(data.get("index", -1)),
                        "name": data.get("name", "Unknown"),
                        "is_running": bool(data.get("is_running", False)),
                        "adb_port": self.get_adb_port(int(data.get("index", -1)))
                    }
                    emulators.append(emulator_info)

            except json.JSONDecodeError:
                # Пробуем парсить текстовый формат
                # Формат: index,name,top_window_title,top_window_handle,is_running
                parts = line.split(',')
                if len(parts) >= 5:
                    try:
                        index = int(parts[0])
                        name = parts[1]
                        is_running_str = parts[4].strip().lower()
                        is_running = is_running_str in ['true', '1', 'yes']

                        emulator_info = {
                            "index": index,
                            "name": name,
                            "is_running": is_running,
                            "adb_port": self.get_adb_port(index)
                        }
                        emulators.append(emulator_info)

                    except (ValueError, IndexError) as e:
                        logger.debug(f"Не удалось парсить строку: {line}, ошибка: {e}")
                        continue

        logger.debug(f"Найдено {len(emulators)} эмуляторов")
        return emulators

    def get_emulator_info(self, index: int) -> Optional[dict]:
        """
        Получение информации о конкретном эмуляторе

        Args:
            index: Индекс эмулятора

        Returns:
            Словарь с информацией об эмуляторе или None если не найден
        """
        logger.debug(f"Получаем информацию об эмуляторе {index}...")

        # Получаем список всех эмуляторов
        all_emulators = self.get_emulator_list()

        # Ищем нужный эмулятор
        for emu in all_emulators:
            if emu["index"] == index:
                logger.debug(f"Информация об эмуляторе {index}: {emu}")
                return emu

        logger.warning(f"Эмулятор с индексом {index} не найден")
        return None

    def get_running_emulators(self) -> list[dict]:
        """
        Получение списка только запущенных эмуляторов

        Returns:
            Список словарей с информацией о запущенных эмуляторах
        """
        all_emulators = self.get_emulator_list()
        running = [emu for emu in all_emulators if emu["is_running"]]

        logger.debug(f"Запущенных эмуляторов: {len(running)}")
        return running

    def force_kill_emulator(self, index: int) -> bool:
        """
        Принудительное завершение эмулятора через killall

        Args:
            index: Индекс эмулятора

        Returns:
            True если команда выполнена успешно, False иначе
        """
        logger.warning(f"Принудительное завершение эмулятора {index}...")

        success, output = self._execute_ldconsole_command(f"killall --index {index}", timeout=10.0)

        if success:
            logger.info(f"Команда принудительного завершения эмулятора {index} выполнена")
            # Даем время на завершение процессов
            time.sleep(3)
            return True
        else:
            logger.error(f"Не удалось принудительно завершить эмулятор {index}: {output}")
            return False

    def wait_for_shutdown(self, index: int, timeout: float = 30.0) -> bool:
        """
        Ожидание полной остановки эмулятора

        Args:
            index: Индекс эмулятора
            timeout: Максимальное время ожидания в секундах

        Returns:
            True если эмулятор остановлен, False иначе
        """
        logger.info(f"Ожидаем полной остановки эмулятора {index}...")

        start_time = time.time()
        check_interval = 2.0

        while time.time() - start_time < timeout:
            if not self.is_running(index):
                elapsed = time.time() - start_time
                logger.success(f"Эмулятор {index} полностью остановлен через {elapsed:.1f}с")
                return True

            time.sleep(check_interval)
            elapsed = time.time() - start_time
            logger.debug(f"Эмулятор {index} еще работает, прошло {elapsed:.1f}с...")

        logger.error(f"Эмулятор {index} не остановился за {timeout}с")
        return False

    def restart_emulator(self, index: int, timeout: float = 90.0) -> bool:
        """
        Перезапуск эмулятора

        Args:
            index: Индекс эмулятора
            timeout: Таймаут для запуска после остановки

        Returns:
            True если перезапуск успешен, False иначе
        """
        logger.info(f"Перезапускаем эмулятор {index}...")

        # Останавливаем эмулятор
        if self.is_running(index):
            if not self.stop_emulator(index):
                logger.warning(f"Не удалось корректно остановить эмулятор {index}, пробуем принудительно")
                if not self.force_kill_emulator(index):
                    logger.error(f"Не удалось остановить эмулятор {index}")
                    return False

            # Ждем полной остановки
            if not self.wait_for_shutdown(index, 20.0):
                logger.error(f"Эмулятор {index} не остановился для перезапуска")
                return False

        # Небольшая пауза между остановкой и запуском
        time.sleep(2)

        # Запускаем эмулятор
        if self.start_emulator(index, wait_ready=True, timeout=timeout):
            logger.success(f"Эмулятор {index} успешно перезапущен")
            return True
        else:
            logger.error(f"Не удалось запустить эмулятор {index} после остановки")
            return False

    def get_status_summary(self) -> dict:
        """
        Получение сводки по статусу всех эмуляторов

        Returns:
            Словарь со сводной информацией
        """
        all_emulators = self.get_emulator_list()
        running_emulators = [emu for emu in all_emulators if emu["is_running"]]

        summary = {
            "total_emulators": len(all_emulators),
            "running_emulators": len(running_emulators),
            "stopped_emulators": len(all_emulators) - len(running_emulators),
            "ldconsole_available": self.ldconsole_path is not None and self.ldconsole_path.exists(),
            "ldconsole_path": str(self.ldconsole_path) if self.ldconsole_path else None,
            "running_details": running_emulators
        }

        logger.debug(f"Сводка статуса: {summary['running_emulators']}/{summary['total_emulators']} запущено")
        return summary