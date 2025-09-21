"""
Оркестратор для управления эмуляторами Beast Lord Bot.
Предоставляет CLI интерфейс для управления эмуляторами с интеграцией умного планировщика и прайм-таймов.
"""

import sys
import time
from pathlib import Path
from typing import List
from datetime import datetime

import click
from loguru import logger
from utils.emulator_discovery import EmulatorDiscovery
from utils.smart_ldconsole import SmartLDConsole
from scheduler import SmartScheduler, get_scheduler
from utils.prime_time_manager import PrimeTimeManager
from utils.database import database


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

        self.ldconsole = SmartLDConsole(ldconsole_path)

        # Инициализируем планировщик с прайм-таймами
        self.scheduler = get_scheduler(database)
        self.prime_time_manager = PrimeTimeManager()

        logger.info("Инициализирован Orchestrator с интеграцией прайм-таймов и умного планировщика")

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

    def process_emulators_with_scheduler(self, max_concurrent: int = 5):
        """
        Основной цикл обработки эмуляторов с использованием SmartScheduler

        Args:
            max_concurrent: Максимальное количество одновременно обрабатываемых эмуляторов
        """
        logger.info("=== ЗАПУСК ОБРАБОТКИ С УМНЫМ ПЛАНИРОВЩИКОМ ===")

        while True:
            try:
                # Получаем готовых эмуляторов по приоритету
                ready_emulators = self.scheduler.get_ready_emulators_by_priority(max_concurrent)

                if not ready_emulators:
                    logger.info("Нет готовых эмуляторов, ждем 5 минут...")
                    time.sleep(300)
                    continue

                logger.info(f"Обрабатываем {len(ready_emulators)} эмуляторов по приоритету...")

                for priority in ready_emulators:
                    logger.info(f"Обрабатываем эмулятор {priority.emulator_index} (приоритет {priority.total_priority})")

                    # Здесь будет интеграция с bot_worker.py
                    # success = process_single_emulator(priority)
                    logger.info(f"[ЗАГЛУШКА] Обработка эмулятора {priority.emulator_index} (bot_worker будет в следующих промптах)")

                    # Обновляем расписание после обработки
                    self.scheduler.update_emulator_schedule(priority.emulator_id, priority)

                # Пауза между циклами
                time.sleep(60)

            except KeyboardInterrupt:
                logger.info("Остановка по запросу пользователя")
                break
            except Exception as e:
                logger.error(f"Ошибка в основном цикле: {e}")
                time.sleep(60)


# Создаем глобальный экземпляр оркестратора
orchestrator = Orchestrator()


@click.group()
@click.version_option(version='1.0.0')
def cli():
    """Beast Lord Bot - Оркестратор управления эмуляторами"""
    pass


# === КОМАНДЫ УПРАВЛЕНИЯ ЭМУЛЯТОРАМИ ===

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
    emulator_ids = tuple(emulator_ids)
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
    emulator_ids = tuple(emulator_ids)
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


# === КОМАНДЫ ПЛАНИРОВЩИКА И ПРАЙМ-ТАЙМОВ ===

@cli.command()
@click.option('--max-concurrent', default=5, help='Максимум одновременно обрабатываемых эмуляторов')
def queue(max_concurrent: int):
    """Показать очередь эмуляторов по приоритету с учетом прайм-таймов"""
    logger.info(f"=== ОЧЕРЕДЬ ЭМУЛЯТОРОВ (макс {max_concurrent}) ===")

    # Получаем готовых эмуляторов по приоритету
    ready_emulators = orchestrator.scheduler.get_ready_emulators_by_priority(max_concurrent)

    if not ready_emulators:
        logger.info("Нет эмуляторов готовых к обработке")
        return

    logger.info(f"Готовых к обработке: {len(ready_emulators)}")

    for i, priority in enumerate(ready_emulators, 1):
        logger.info(f"\n{i}. Эмулятор {priority.emulator_index}: {priority.emulator_name}")
        logger.info(f"   Лорд {priority.lord_level} | Приоритет: {priority.total_priority}")

        # Показываем факторы приоритета
        logger.info("   Факторы приоритета:")
        for factor, value in priority.priority_factors.items():
            if value > 0:
                logger.info(f"     - {factor}: +{value}")

        # Показываем рекомендуемые действия
        if priority.recommended_actions:
            logger.info(f"   Рекомендуемые действия: {', '.join(priority.recommended_actions[:3])}")

        # Показываем информацию о прайм-тайме
        if priority.waiting_for_prime_time and priority.next_prime_time_window:
            wait_time = (priority.next_prime_time_window - datetime.now()).total_seconds() / 3600
            logger.info(f"   🕐 Ожидает прайм-тайм через {wait_time:.1f}ч")


@cli.command()
@click.option('--detailed', is_flag=True, help='Детальная информация')
def schedule(detailed: bool):
    """Показать расписание и статус планирования"""
    logger.info("=== РАСПИСАНИЕ И ПЛАНИРОВАНИЕ ===")

    # Получаем сводку по расписанию
    summary = orchestrator.scheduler.get_schedule_summary()

    logger.info(f"📊 Включенных эмуляторов: {summary['total_enabled']}")
    logger.info(f"✅ Готовы сейчас: {summary['ready_now']}")
    logger.info(f"⏰ Ждут времени: {summary['waiting_for_time']}")
    logger.info(f"🎯 Ждут прайм-тайм: {summary['waiting_for_prime_time']}")

    if summary['highest_priority'] > 0:
        logger.info(f"🔥 Максимальный приоритет: {summary['highest_priority']}")

    if summary['next_ready_time']:
        logger.info(f"⏰ Следующий готов: {summary['next_ready_time']}")

    # Показываем статус прайм-таймов
    prime_status = summary['prime_time_status']
    logger.info(f"\n🎯 ПРАЙМ-ТАЙМЫ:")
    logger.info(f"Текущее время: {prime_status['current_time']}")
    logger.info(f"Период обновления: {'Да' if prime_status['is_maintenance_period'] else 'Нет'}")
    logger.info(f"Активных сейчас: {prime_status['current_active']}")

    if prime_status['current_actions']:
        logger.info("Текущие прайм-таймы:")
        for action in prime_status['current_actions']:
            logger.info(f"  - {action}")

    if detailed and summary['ready_now'] > 0:
        logger.info(f"\n=== ДЕТАЛЬНАЯ ИНФОРМАЦИЯ ===")
        # Показываем детали по готовым эмуляторам
        ready_emulators = orchestrator.scheduler.get_ready_emulators_by_priority(10)

        for priority in ready_emulators:
            logger.info(f"\nЭмулятор {priority.emulator_index}: {priority.emulator_name}")
            logger.info(f"  Лорд: {priority.lord_level} | Приоритет: {priority.total_priority}")

            if priority.priority_factors:
                logger.info("  Приоритеты:")
                for factor, value in priority.priority_factors.items():
                    logger.info(f"    {factor}: {value}")

            if priority.next_check_time:
                logger.info(f"  Следующая проверка: {priority.next_check_time.strftime('%H:%M')}")


@cli.command()
@click.option('--action-type', required=True,
              type=click.Choice(['building_power', 'evolution_bonus', 'training_bonus', 'resource_bonus', 'special_services']),
              help='Тип действия для проверки прайм-тайма')
def prime_time(action_type: str):
    """Проверить статус прайм-тайма для конкретного типа действий"""
    logger.info(f"=== ПРАЙМ-ТАЙМ ДЛЯ {action_type.upper()} ===")

    # Проверяем текущий статус
    is_active, active_actions = orchestrator.prime_time_manager.is_prime_time_active([action_type])

    if is_active:
        logger.success(f"✅ Прайм-тайм для {action_type} АКТИВЕН!")
        logger.info("Активные действия:")
        for action in active_actions:
            logger.info(f"  - {action.bonus_description}")
    else:
        logger.info(f"❌ Прайм-тайм для {action_type} не активен")

        # Ищем следующий прайм-тайм
        next_window = orchestrator.prime_time_manager.get_next_prime_window([action_type])

        if next_window:
            next_time, next_actions = next_window
            wait_hours = (next_time - datetime.now()).total_seconds() / 3600
            day_name = ['ПН', 'ВТ', 'СР', 'ЧТ', 'ПТ', 'СБ', 'ВС'][next_time.weekday()]

            logger.info(f"⏰ Следующий прайм-тайм: {day_name} {next_time.strftime('%H:%M')} (через {wait_hours:.1f}ч)")
            logger.info("Действия:")
            for action in next_actions:
                logger.info(f"  - {action.bonus_description}")
        else:
            logger.warning("Следующий прайм-тайм не найден в ближайшие 7 дней")

    # Проверяем стоит ли ждать
    should_wait, wait_time = orchestrator.prime_time_manager.should_wait_for_prime_time([action_type])

    if should_wait and wait_time:
        wait_hours = (wait_time - datetime.now()).total_seconds() / 3600
        logger.info(f"💡 Рекомендация: ЖДАТЬ прайм-тайм (через {wait_hours:.1f}ч)")
    else:
        logger.info(f"💡 Рекомендация: НЕ ждать, действовать сейчас")


@cli.command()
@click.option('--emulator-id', type=int, help='ID конкретного эмулятора')
def priority(emulator_id: int = None):
    """Показать расчет приоритета эмуляторов"""
    if emulator_id is not None:
        # Показываем приоритет конкретного эмулятора
        logger.info(f"=== ПРИОРИТЕТ ЭМУЛЯТОРА {emulator_id} ===")

        emulator_data = orchestrator.discovery.get_emulator(emulator_id)
        if not emulator_data:
            logger.error(f"Эмулятор {emulator_id} не найден")
            return

        # Получаем данные из БД
        db_emulator = database.get_emulator(emulator_id)
        if not db_emulator:
            logger.error(f"Данные эмулятора {emulator_id} не найдены в БД")
            return

        # Рассчитываем приоритет
        priority = orchestrator.scheduler.calculate_emulator_priority(db_emulator)

        logger.info(f"Эмулятор: {priority.emulator_name}")
        logger.info(f"Лорд: {priority.lord_level}")
        logger.info(f"Общий приоритет: {priority.total_priority}")

        logger.info("\nДетализация приоритета:")
        for factor, value in priority.priority_factors.items():
            logger.info(f"  {factor}: {value}")

        if priority.recommended_actions:
            logger.info(f"\nРекомендуемые действия:")
            for action in priority.recommended_actions:
                logger.info(f"  - {action}")

        if priority.next_check_time:
            logger.info(f"\nСледующая проверка: {priority.next_check_time.strftime('%Y-%m-%d %H:%M')}")

        if priority.waiting_for_prime_time:
            logger.info(f"🕐 Ожидает прайм-тайм: {priority.next_prime_time_window.strftime('%Y-%m-%d %H:%M') if priority.next_prime_time_window else 'неизвестно'}")

    else:
        # Показываем приоритеты всех готовых эмуляторов
        logger.info("=== ПРИОРИТЕТЫ ВСЕХ ГОТОВЫХ ЭМУЛЯТОРОВ ===")

        ready_emulators = orchestrator.scheduler.get_ready_emulators_by_priority(20)

        if not ready_emulators:
            logger.info("Нет эмуляторов готовых к обработке")
            return

        logger.info(f"Найдено {len(ready_emulators)} готовых эмуляторов:")

        for i, priority in enumerate(ready_emulators, 1):
            logger.info(f"\n{i}. ID {priority.emulator_index}: {priority.total_priority} баллов")

            # Показываем топ-3 фактора приоритета
            sorted_factors = sorted(priority.priority_factors.items(), key=lambda x: x[1], reverse=True)
            for factor, value in sorted_factors[:3]:
                if value > 0:
                    logger.info(f"   - {factor}: {value}")


@cli.command()
@click.option('--id', 'emulator_id', type=int, required=True, help='ID эмулятора')
def update_schedule(emulator_id: int):
    """Принудительно обновить расписание эмулятора"""
    logger.info(f"=== ОБНОВЛЕНИЕ РАСПИСАНИЯ ЭМУЛЯТОРА {emulator_id} ===")

    # Получаем данные эмулятора
    db_emulator = database.get_emulator(emulator_id)
    if not db_emulator:
        logger.error(f"Эмулятор {emulator_id} не найден в БД")
        return

    # Рассчитываем новый приоритет
    priority = orchestrator.scheduler.calculate_emulator_priority(db_emulator)

    # Обновляем в БД
    if orchestrator.scheduler.update_emulator_schedule(db_emulator['id'], priority):
        logger.success(f"Расписание эмулятора {emulator_id} обновлено")

        logger.info(f"Новый приоритет: {priority.total_priority}")
        if priority.next_check_time:
            logger.info(f"Следующая проверка: {priority.next_check_time.strftime('%Y-%m-%d %H:%M')}")
        if priority.waiting_for_prime_time:
            logger.info(f"Ожидает прайм-тайм: {priority.next_prime_time_window.strftime('%Y-%m-%d %H:%M') if priority.next_prime_time_window else 'неизвестно'}")
    else:
        logger.error(f"Не удалось обновить расписание эмулятора {emulator_id}")


# === КОМАНДЫ ОБРАБОТКИ ===

@cli.command()
@click.option('--max-concurrent', default=5, help='Максимум одновременно обрабатываемых эмуляторов')
def start_processing(max_concurrent: int):
    """Запустить обработку эмуляторов с умным планировщиком"""
    logger.info(f"=== ЗАПУСК ОБРАБОТКИ (макс {max_concurrent} одновременно) ===")

    try:
        orchestrator.process_emulators_with_scheduler(max_concurrent)
    except KeyboardInterrupt:
        logger.info("Обработка остановлена по запросу пользователя")
    except Exception as e:
        logger.error(f"Критическая ошибка в обработке: {e}")


@cli.command()
def stop_processing():
    """Остановить обработку эмуляторов"""
    logger.info("=== ОСТАНОВКА ОБРАБОТКИ ===")
    logger.info("Для остановки используйте Ctrl+C в процессе обработки")
    logger.info("Команда будет расширена в следующих промптах")


# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===

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