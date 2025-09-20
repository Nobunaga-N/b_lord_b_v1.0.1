"""
Модуль автообнаружения и управления эмуляторами LDPlayer.
Сканирует доступные эмуляторы и получает их реальные ADB порты.
"""

import os
import re
import subprocess
import json
from typing import List, Dict, Optional, Tuple
from pathlib import Path

import yaml
from loguru import logger


class EmulatorInfo:
    """Информация об эмуляторе"""

    def __init__(self, index: int, name: str, adb_port: int,
                 enabled: bool = False, notes: str = ""):
        self.index = index
        self.name = name
        self.adb_port = adb_port
        self.enabled = enabled
        self.notes = notes

    def to_dict(self) -> dict:
        """Конвертация в словарь для сохранения"""
        return {
            "index": self.index,
            "name": self.name,
            "adb_port": self.adb_port,
            "enabled": self.enabled,
            "notes": self.notes
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EmulatorInfo":
        """Создание из словаря"""
        return cls(
            index=data["index"],
            name=data["name"],
            adb_port=data["adb_port"],
            enabled=data.get("enabled", False),
            notes=data.get("notes", "")
        )


class EmulatorDiscovery:
    """Класс для автообнаружения и управления эмуляторами LDPlayer"""

    def __init__(self, config_path: str = "configs/emulators.yaml"):
        """
        Инициализация менеджера эмуляторов

        Args:
            config_path: Путь к файлу конфигурации эмуляторов
        """
        self.config_path = Path(config_path)
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

        self.ldconsole_path: Optional[Path] = None
        self.emulators: Dict[int, EmulatorInfo] = {}

        logger.info(f"Инициализирован EmulatorDiscovery, конфиг: {self.config_path}")

    def find_ldplayer_path(self) -> Optional[Path]:
        """
        Поиск пути к ldconsole.exe по стандартным расположениям

        Returns:
            Путь к ldconsole.exe или None если не найден
        """
        logger.info("Ищем ldconsole.exe...")

        # Стандартные пути установки LDPlayer
        possible_paths = [
            # LDPlayer 4
            Path("C:/LDPlayer/LDPlayer4.0/ldconsole.exe"),
            Path("C:/LDPlayer4.0/ldconsole.exe"),
            Path("D:/LDPlayer/LDPlayer4.0/ldconsole.exe"),
            Path("D:/LDPlayer4.0/ldconsole.exe"),

            # LDPlayer 9
            Path("C:/LDPlayer/LDPlayer9/ldconsole.exe"),
            Path("C:/LDPlayer9/ldconsole.exe"),
            Path("D:/LDPlayer/LDPlayer9/ldconsole.exe"),
            Path("D:/LDPlayer9/ldconsole.exe"),

            # Из переменной PATH
            Path("ldconsole.exe"),
        ]

        # Проверяем каждый путь
        for path in possible_paths:
            try:
                if path.name == "ldconsole.exe" and path.parent == Path("."):
                    # Проверяем в PATH
                    result = subprocess.run(
                        ["where", "ldconsole.exe"],
                        capture_output=True,
                        text=True,
                        shell=True
                    )
                    if result.returncode == 0:
                        found_path = Path(result.stdout.strip().split('\n')[0])
                        if found_path.exists():
                            logger.success(f"ldconsole.exe найден в PATH: {found_path}")
                            self.ldconsole_path = found_path
                            return found_path
                else:
                    # Проверяем прямой путь
                    if path.exists():
                        logger.success(f"ldconsole.exe найден: {path}")
                        self.ldconsole_path = path
                        return path

            except Exception as e:
                logger.debug(f"Ошибка при проверке пути {path}: {e}")

        logger.error("ldconsole.exe не найден в стандартных местах")
        return None

    def scan_emulators(self) -> bool:
        """
        Сканирование доступных эмуляторов через ldconsole list2

        Returns:
            True если сканирование успешно, False иначе
        """
        logger.info("Сканируем доступные эмуляторы...")

        # Находим ldconsole если еще не найден
        if not self.ldconsole_path:
            if not self.find_ldplayer_path():
                logger.error("Не удалось найти ldconsole.exe")
                return False

        try:
            # Выполняем команду list2 для получения списка эмуляторов
            result = subprocess.run(
                [str(self.ldconsole_path), "list2"],
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode != 0:
                logger.error(f"Ошибка выполнения ldconsole list2: {result.stderr}")
                return False

            # Парсим вывод ldconsole list2
            emulators_data = self._parse_ldconsole_output(result.stdout)

            if not emulators_data:
                logger.warning("Не найдено эмуляторов LDPlayer")
                return True

            # Получаем реальные ADB порты для каждого эмулятора
            for emu_data in emulators_data:
                adb_port = self._get_real_adb_port(emu_data["index"])

                if adb_port:
                    # Сохраняем пользовательские настройки если эмулятор уже существует
                    existing_info = self.emulators.get(emu_data["index"])
                    enabled = existing_info.enabled if existing_info else False
                    notes = existing_info.notes if existing_info else "Требует настройки"

                    # Создаем информацию об эмуляторе
                    emulator_info = EmulatorInfo(
                        index=emu_data["index"],
                        name=emu_data["name"],
                        adb_port=adb_port,
                        enabled=enabled,
                        notes=notes
                    )

                    self.emulators[emu_data["index"]] = emulator_info
                    logger.info(f"Эмулятор {emu_data['index']}: {emu_data['name']} -> ADB порт {adb_port}")
                else:
                    logger.warning(f"Не удалось определить ADB порт для эмулятора {emu_data['index']}")

            logger.success(f"Найдено {len(self.emulators)} эмуляторов")
            return True

        except subprocess.TimeoutExpired:
            logger.error("Таймаут при сканировании эмуляторов")
            return False
        except Exception as e:
            logger.error(f"Ошибка при сканировании эмуляторов: {e}")
            return False

    def _parse_ldconsole_output(self, output: str) -> List[Dict]:
        """
        Парсинг вывода ldconsole list2

        Args:
            output: Вывод команды ldconsole list2

        Returns:
            Список словарей с данными эмуляторов
        """
        emulators = []

        try:
            # ldconsole list2 возвращает JSON
            lines = output.strip().split('\n')
            for line in lines:
                line = line.strip()
                if not line:
                    continue

                try:
                    # Пробуем парсить как JSON
                    data = json.loads(line)
                    if isinstance(data, dict) and "index" in data and "name" in data:
                        emulators.append({
                            "index": int(data["index"]),
                            "name": data["name"]
                        })
                except json.JSONDecodeError:
                    # Если не JSON, пробуем парсить как обычный текст
                    # Формат: index,name,top_window_title,top_window_handle,is_running
                    parts = line.split(',')
                    if len(parts) >= 2:
                        try:
                            index = int(parts[0])
                            name = parts[1]
                            emulators.append({
                                "index": index,
                                "name": name
                            })
                        except ValueError:
                            continue

        except Exception as e:
            logger.error(f"Ошибка парсинга вывода ldconsole: {e}")

        return emulators

    def _get_real_adb_port(self, emulator_index: int) -> Optional[int]:
        """
        Получение реального ADB порта для эмулятора

        Args:
            emulator_index: Индекс эмулятора

        Returns:
            ADB порт или None если не удалось определить
        """
        try:
            # Способ 1: Проверяем подключенные ADB устройства
            adb_port = self._get_port_from_adb_devices(emulator_index)
            if adb_port:
                logger.debug(f"Порт {adb_port} найден через adb devices для эмулятора {emulator_index}")
                return adb_port

            # Способ 2: Пробуем стандартные формулы (БЕЗ тестирования пока эмуляторы выключены)
            possible_ports = [
                5554 + emulator_index * 2,  # Основная формула пользователя
                5556 + emulator_index * 2,  # Альтернативная формула 1
                5555 + emulator_index * 2,  # Альтернативная формула 2
            ]

            logger.debug(f"Пробуем порты для эмулятора {emulator_index}: {possible_ports}")

            # Сначала пробуем основную формулу без тестирования (так как эмуляторы могут быть выключены)
            preferred_port = possible_ports[0]  # 5554 + index * 2
            logger.debug(f"Используем предпочтительный порт {preferred_port} для эмулятора {emulator_index}")
            return preferred_port

        except Exception as e:
            logger.error(f"Ошибка при определении ADB порта: {e}")
            # В случае ошибки используем основную формулу
            return 5554 + emulator_index * 2

    def _get_port_from_adb_devices(self, emulator_index: int) -> Optional[int]:
        """
        Получение ADB порта из списка подключенных устройств

        Args:
            emulator_index: Индекс эмулятора

        Returns:
            ADB порт или None
        """
        try:
            # Получаем список подключенных устройств
            result = subprocess.run(
                ["adb", "devices"],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode != 0:
                logger.debug("adb devices завершился с ошибкой")
                return None

            logger.debug(f"adb devices output:\n{result.stdout}")

            # Собираем все найденные порты
            found_ports = []
            for line in result.stdout.split('\n'):
                if 'emulator' in line or '127.0.0.1:' in line:
                    # Извлекаем порт из строки типа "127.0.0.1:5554	device"
                    match = re.search(r'127\.0\.0\.1:(\d+)', line)
                    if match:
                        port = int(match.group(1))
                        found_ports.append(port)

            logger.debug(f"Найденные ADB порты: {found_ports}")

            # Пытаемся сопоставить порт с индексом эмулятора
            # Предполагаем стандартную формулу 5554 + index * 2
            expected_port = 5554 + emulator_index * 2
            if expected_port in found_ports:
                logger.debug(f"Найден ожидаемый порт {expected_port} для эмулятора {emulator_index}")
                return expected_port

            return None

        except Exception as e:
            logger.debug(f"Ошибка при получении портов из adb devices: {e}")
            return None

    def _test_adb_port(self, port: int) -> bool:
        """
        Тестирование ADB порта на доступность

        Args:
            port: Порт для тестирования

        Returns:
            True если порт доступен, False иначе
        """
        try:
            result = subprocess.run(
                ["adb", "connect", f"127.0.0.1:{port}"],
                capture_output=True,
                text=True,
                timeout=5
            )

            if "connected" in result.stdout or "already connected" in result.stdout:
                return True

            return False

        except Exception:
            return False

    def save_config(self) -> bool:
        """
        Сохранение конфигурации эмуляторов в YAML файл

        Returns:
            True если сохранение успешно, False иначе
        """
        try:
            config_data = {
                "emulators": [emu.to_dict() for emu in self.emulators.values()],
                "ldconsole_path": str(self.ldconsole_path) if self.ldconsole_path else None,
                "last_scan": None  # Можно добавить timestamp
            }

            with open(self.config_path, 'w', encoding='utf-8') as f:
                yaml.dump(config_data, f, default_flow_style=False,
                         allow_unicode=True, sort_keys=False)

            logger.success(f"Конфигурация эмуляторов сохранена: {self.config_path}")
            return True

        except Exception as e:
            logger.error(f"Ошибка при сохранении конфигурации: {e}")
            return False

    def load_config(self) -> bool:
        """
        Загрузка конфигурации эмуляторов из YAML файла

        Returns:
            True если загрузка успешна, False иначе
        """
        try:
            if not self.config_path.exists():
                logger.info("Файл конфигурации не найден, будет создан при первом сканировании")
                return True

            with open(self.config_path, 'r', encoding='utf-8') as f:
                config_data = yaml.safe_load(f)

            if not config_data:
                return True

            # Загружаем путь к ldconsole
            if config_data.get("ldconsole_path"):
                self.ldconsole_path = Path(config_data["ldconsole_path"])

            # Загружаем эмуляторы
            self.emulators = {}
            for emu_data in config_data.get("emulators", []):
                emulator_info = EmulatorInfo.from_dict(emu_data)
                self.emulators[emulator_info.index] = emulator_info

            logger.info(f"Загружена конфигурация {len(self.emulators)} эмуляторов")
            return True

        except Exception as e:
            logger.error(f"Ошибка при загрузке конфигурации: {e}")
            return False

    def get_emulators(self) -> Dict[int, EmulatorInfo]:
        """Получение всех эмуляторов"""
        return self.emulators.copy()

    def get_emulator(self, index: int) -> Optional[EmulatorInfo]:
        """Получение информации о конкретном эмуляторе"""
        return self.emulators.get(index)

    def enable_emulator(self, index: int) -> bool:
        """
        Включение эмулятора

        Args:
            index: Индекс эмулятора

        Returns:
            True если успешно, False иначе
        """
        if index not in self.emulators:
            logger.error(f"Эмулятор с индексом {index} не найден")
            return False

        self.emulators[index].enabled = True
        logger.info(f"Эмулятор {index} ({self.emulators[index].name}) включен")
        return True

    def disable_emulator(self, index: int) -> bool:
        """
        Выключение эмулятора

        Args:
            index: Индекс эмулятора

        Returns:
            True если успешно, False иначе
        """
        if index not in self.emulators:
            logger.error(f"Эмулятор с индексом {index} не найден")
            return False

        self.emulators[index].enabled = False
        logger.info(f"Эмулятор {index} ({self.emulators[index].name}) выключен")
        return True

    def update_notes(self, index: int, notes: str) -> bool:
        """
        Обновление заметок для эмулятора

        Args:
            index: Индекс эмулятора
            notes: Новые заметки

        Returns:
            True если успешно, False иначе
        """
        if index not in self.emulators:
            logger.error(f"Эмулятор с индексом {index} не найден")
            return False

        self.emulators[index].notes = notes
        logger.info(f"Заметки для эмулятора {index} обновлены: {notes}")
        return True

    def get_enabled_emulators(self) -> Dict[int, EmulatorInfo]:
        """
        Получение только включенных эмуляторов

        Returns:
            Словарь включенных эмуляторов
        """
        enabled = {idx: emu for idx, emu in self.emulators.items() if emu.enabled}
        logger.debug(f"Включенных эмуляторов: {len(enabled)}")
        return enabled

    def get_disabled_emulators(self) -> Dict[int, EmulatorInfo]:
        """
        Получение только выключенных эмуляторов

        Returns:
            Словарь выключенных эмуляторов
        """
        disabled = {idx: emu for idx, emu in self.emulators.items() if not emu.enabled}
        logger.debug(f"Выключенных эмуляторов: {len(disabled)}")
        return disabled

    def rescan_with_user_settings(self) -> bool:
        """
        Пересканирование с сохранением пользовательских настроек

        Returns:
            True если успешно, False иначе
        """
        logger.info("Пересканирование эмуляторов с сохранением настроек...")

        # Сохраняем текущие пользовательские настройки
        old_settings = {}
        for idx, emu in self.emulators.items():
            old_settings[idx] = {
                "enabled": emu.enabled,
                "notes": emu.notes
            }

        # Выполняем новое сканирование
        if not self.scan_emulators():
            logger.error("Ошибка при пересканировании")
            return False

        # Восстанавливаем пользовательские настройки
        for idx, emu in self.emulators.items():
            if idx in old_settings:
                emu.enabled = old_settings[idx]["enabled"]
                emu.notes = old_settings[idx]["notes"]
                logger.debug(f"Восстановлены настройки для эмулятора {idx}")

        # Сохраняем обновленную конфигурацию
        self.save_config()

        logger.success("Пересканирование завершено с сохранением настроек")
        return True

    def get_status_summary(self) -> dict:
        """
        Получение сводки по статусу эмуляторов

        Returns:
            Словарь со сводкой
        """
        enabled_count = len(self.get_enabled_emulators())
        disabled_count = len(self.get_disabled_emulators())
        total_count = len(self.emulators)

        return {
            "total": total_count,
            "enabled": enabled_count,
            "disabled": disabled_count,
            "ldconsole_found": self.ldconsole_path is not None,
            "ldconsole_path": str(self.ldconsole_path) if self.ldconsole_path else None
        }