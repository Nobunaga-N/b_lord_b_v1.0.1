"""
Оркестратор для управления эмуляторами Beast Lord Bot.
Предоставляет CLI интерфейс для управления эмуляторами.
"""

import sys
from pathlib import Path
from typing import List

import click
from loguru import logger
from utils.emulator_discovery import EmulatorDiscovery
from utils.smart_ldconsole import SmartLDConsole


class Orchestrator:
    """Основной класс оркестратора"""

    def __init__(self):
        """Инициализация оркестратора"""
        self.discovery = EmulatorDiscovery()

        # Настройка логирования
        self._setup_logging()

        # Загружаем конфигурацию эмуляторов для получения пути к ldconsole
        self.discovery.load_config()

        # Инициализируем SmartLDConsole с найденным путем
        ldconsole_path = None
        if self.discovery.ldconsole_path:
            ldconsole_path = self.discovery.ldconsole_path

        self.ldconsole = SmartLDConsole(ldconsole_path)  # <-- ДОБАВЛЕНА ЭТА СТРОКА

        logger.info("Инициализирован Orchestrator")

    def _setup_logging(self):
        """Настройка системы логирования"""
        # Удаляем стандартный обработчик
        logger.remove()

        # Добавляем консольный вывод
        logger.add(
            sys.stdout,
            format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
            level="INFO"
        )

        # Создаем директорию для логов
        logs_dir = Path("data/logs")
        logs_dir.mkdir(parents=True, exist_ok=True)

        # Добавляем запись в файл
        logger.add(
            logs_dir / "orchestrator.log",
            rotation="1 day",
            retention="7 days",
            level="DEBUG",
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}"
        )


# Создаем глобальный экземпляр оркестратора
orchestrator = Orchestrator()


@click.group()
@click.version_option(version='1.0.0')
def cli():
    """Beast Lord Bot - Оркестратор управления эмуляторами"""
    pass


@cli.command()
def scan():
    """Сканирование доступных эмуляторов LDPlayer"""
    logger.info("=== Сканирование эмуляторов ===")

    # Загружаем существующую конфигурацию
    orchestrator.discovery.load_config()

    # Выполняем пересканирование с сохранением настроек
    if orchestrator.discovery.rescan_with_user_settings():
        # Показываем результаты
        summary = orchestrator.discovery.get_status_summary()

        logger.success("Сканирование завершено успешно!")
        logger.info(f"Найдено эмуляторов: {summary['total']}")
        logger.info(f"Включено: {summary['enabled']}")
        logger.info(f"Выключено: {summary['disabled']}")

        if summary['ldconsole_found']:
            logger.info(f"LDConsole: {summary['ldconsole_path']}")
        else:
            logger.warning("LDConsole не найден!")

        # Показываем список эмуляторов
        _show_emulators_list(detailed=False)

    else:
        logger.error("Ошибка при сканировании эмуляторов")
        sys.exit(1)


@cli.command()
@click.option('--enabled-only', is_flag=True, help='Показать только включенные эмуляторы')
@click.option('--disabled-only', is_flag=True, help='Показать только выключенные эмуляторы')
@click.option('--detailed', is_flag=True, help='Подробная информация')
def list(enabled_only: bool, disabled_only: bool, detailed: bool):
    """Список всех эмуляторов"""
    logger.info("=== Список эмуляторов ===")

    # Загружаем конфигурацию
    if not orchestrator.discovery.load_config():
        logger.error("Не удалось загрузить конфигурацию. Выполните сначала 'scan'")
        sys.exit(1)

    _show_emulators_list(enabled_only, disabled_only, detailed)


@cli.command()
@click.option('--id', 'emulator_ids', multiple=True, type=int, required=True,
              help='ID эмулятора для включения (можно указать несколько)')
def enable(emulator_ids: List[int]):
    """Включение эмулятора(ов)"""
    emulator_ids = tuple(emulator_ids)  # Безопасная конвертация
    logger.info(f"=== Включение эмуляторов: {emulator_ids} ===")

    # Загружаем конфигурацию
    if not orchestrator.discovery.load_config():
        logger.error("Не удалось загрузить конфигурацию. Выполните сначала 'scan'")
        sys.exit(1)

    success_count = 0
    for emu_id in emulator_ids:
        if orchestrator.discovery.enable_emulator(emu_id):
            success_count += 1
        else:
            logger.error(f"Не удалось включить эмулятор {emu_id}")

    if success_count > 0:
        # Сохраняем изменения
        orchestrator.discovery.save_config()
        logger.success(f"Включено эмуляторов: {success_count}/{len(emulator_ids)}")
    else:
        logger.error("Не удалось включить ни одного эмулятора")
        sys.exit(1)


@cli.command()
@click.option('--id', 'emulator_ids', multiple=True, type=int, required=True,
              help='ID эмулятора для выключения (можно указать несколько)')
def disable(emulator_ids: List[int]):
    """Выключение эмулятора(ов)"""
    emulator_ids = tuple(emulator_ids)  # Безопасная конвертация
    logger.info(f"=== Выключение эмуляторов: {emulator_ids} ===")

    # Загружаем конфигурацию
    if not orchestrator.discovery.load_config():
        logger.error("Не удалось загрузить конфигурацию. Выполните сначала 'scan'")
        sys.exit(1)

    success_count = 0
    for emu_id in emulator_ids:
        if orchestrator.discovery.disable_emulator(emu_id):
            success_count += 1
        else:
            logger.error(f"Не удалось выключить эмулятор {emu_id}")

    if success_count > 0:
        # Сохраняем изменения
        orchestrator.discovery.save_config()
        logger.success(f"Выключено эмуляторов: {success_count}/{len(emulator_ids)}")
    else:
        logger.error("Не удалось выключить ни одного эмулятора")
        sys.exit(1)


@cli.command()
@click.option('--id', 'emulator_id', type=int, required=True, help='ID эмулятора')
@click.option('--text', 'notes_text', required=True, help='Текст заметки')
def note(emulator_id: int, notes_text: str):
    """Обновление заметки для эмулятора"""
    logger.info(f"=== Обновление заметки для эмулятора {emulator_id} ===")

    # Загружаем конфигурацию
    if not orchestrator.discovery.load_config():
        logger.error("Не удалось загрузить конфигурацию. Выполните сначала 'scan'")
        sys.exit(1)

    if orchestrator.discovery.update_notes(emulator_id, notes_text):
        # Сохраняем изменения
        orchestrator.discovery.save_config()
        logger.success(f"Заметка для эмулятора {emulator_id} обновлена")
    else:
        logger.error(f"Не удалось обновить заметку для эмулятора {emulator_id}")
        sys.exit(1)


@cli.command()
def status():
    """Показать общий статус системы"""
    logger.info("=== Статус системы ===")

    # Загружаем конфигурацию
    if not orchestrator.discovery.load_config():
        logger.warning("Конфигурация не найдена. Выполните 'scan' для первоначальной настройки")
        return

    summary = orchestrator.discovery.get_status_summary()

    # Общая информация
    logger.info(f"📊 Всего эмуляторов: {summary['total']}")
    logger.info(f"✅ Включено: {summary['enabled']}")
    logger.info(f"❌ Выключено: {summary['disabled']}")

    if summary['ldconsole_found']:
        logger.info(f"🔧 LDConsole: {summary['ldconsole_path']}")
    else:
        logger.warning("⚠️  LDConsole не найден")

    # Показываем включенные эмуляторы
    if summary['enabled'] > 0:
        logger.info("")
        logger.info("Включенные эмуляторы:")
        enabled = orchestrator.discovery.get_enabled_emulators()
        for idx, emu in enabled.items():
            logger.info(f"  {idx}: {emu.name} (порт {emu.adb_port}) - {emu.notes}")


def _show_emulators_list(enabled_only: bool = False, disabled_only: bool = False,
                        detailed: bool = False):
    """
    Внутренняя функция для отображения списка эмуляторов

    Args:
        enabled_only: Показать только включенные
        disabled_only: Показать только выключенные
        detailed: Подробная информация
    """
    # Определяем какие эмуляторы показывать
    if enabled_only:
        emulators = orchestrator.discovery.get_enabled_emulators()
        title = "Включенные эмуляторы"
    elif disabled_only:
        emulators = orchestrator.discovery.get_disabled_emulators()
        title = "Выключенные эмуляторы"
    else:
        emulators = orchestrator.discovery.get_emulators()
        title = "Все эмуляторы"

    if not emulators:
        logger.info(f"{title}: не найдено")
        return

    logger.info(f"{title}:")

    # Сортируем по индексу
    sorted_emulators = sorted(emulators.items())

    for idx, emu in sorted_emulators:
        status_icon = "✅" if emu.enabled else "❌"

        if detailed:
            logger.info(f"  {status_icon} ID {idx:2d}: {emu.name}")
            logger.info(f"      ADB порт: {emu.adb_port}")
            logger.info(f"      Включен: {'Да' if emu.enabled else 'Нет'}")
            logger.info(f"      Заметки: {emu.notes}")
            logger.info("")
        else:
            logger.info(f"  {status_icon} ID {idx:2d}: {emu.name:15s} (порт {emu.adb_port}) - {emu.notes}")


if __name__ == '__main__':
    cli()