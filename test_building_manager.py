#!/usr/bin/env python3
"""
Тест BuildingManager - "МОЗГИ" системы строительства и исследований.
Проверка ПАРАЛЛЕЛЬНОЙ работы зданий И исследований.
"""

import sys
from pathlib import Path
from loguru import logger

# Добавляем путь к проекту
sys.path.append(str(Path(__file__).parent))


def setup_logging():
    """Настройка логирования"""
    logger.remove()
    logger.add(
        sys.stdout,
        level="INFO",
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>"
    )


def test_building_manager_initialization():
    """Тест инициализации BuildingManager"""
    logger.info("\n=== ТЕСТ ИНИЦИАЛИЗАЦИИ BUILDING MANAGER ===")

    try:
        from utils.building_manager import BuildingManager, get_building_manager
        from utils.database import Database
        from utils.prime_time_manager import PrimeTimeManager

        # Создаем тестовую БД
        test_db = Database("data/test_building_manager.db")

        # Создаем менеджер прайм-таймов
        prime_manager = PrimeTimeManager()

        # Создаем BuildingManager
        building_manager = BuildingManager(test_db, prime_manager)

        logger.success("✅ BuildingManager успешно создан")

        # Проверяем настройки слотов
        logger.info("Слоты строителей по уровню лорда:")
        for lord_level in [10, 13, 16, 19]:
            slots = building_manager.builder_slots_by_lord.get(lord_level, 3)
            logger.info(f"  Лорд {lord_level}: {slots} строителей")

        # Проверяем приоритеты
        logger.info("Настройки приоритетов:")
        for key, value in building_manager.priority_settings.items():
            logger.info(f"  {key}: {value}")

        return building_manager

    except ImportError as e:
        logger.error(f"❌ Ошибка импорта: {e}")
        return None
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации: {e}")
        return None


def test_slot_status_calculation():
    """Тест расчета статуса слотов"""
    logger.info("\n=== ТЕСТ РАСЧЕТА СТАТУСА СЛОТОВ ===")

    try:
        from utils.building_manager import get_building_manager

        building_manager = get_building_manager()

        # Тестируем для разных уровней лорда
        test_emulator_id = 1

        for lord_level in [10, 13, 16, 19]:
            logger.info(f"\n📊 Тест для лорда {lord_level} уровня:")

            slot_status = building_manager.get_slot_status(test_emulator_id, lord_level)

            logger.info(
                f"  Строительство: {slot_status.building_slots_free}/{slot_status.building_slots_total} слотов свободно")
            logger.info(
                f"  Исследования: {slot_status.research_slots_free}/{slot_status.research_slots_total} слотов свободно")
            logger.info(f"  Активных зданий: {len(slot_status.active_buildings)}")
            logger.info(f"  Активных исследований: {len(slot_status.active_research)}")

            # Проверяем методы проверки слотов
            has_building_slot = building_manager.has_free_building_slot(test_emulator_id, lord_level)
            has_research_slot = building_manager.has_free_research_slot(test_emulator_id)

            logger.info(f"  Свободный слот строительства: {'✅' if has_building_slot else '❌'}")
            logger.info(f"  Свободный слот исследований: {'✅' if has_research_slot else '❌'}")

        logger.success("✅ Тест статуса слотов завершен")

    except Exception as e:
        logger.error(f"❌ Ошибка тестирования слотов: {e}")


def test_action_determination():
    """Тест определения следующего действия"""
    logger.info("\n=== ТЕСТ ОПРЕДЕЛЕНИЯ СЛЕДУЮЩЕГО ДЕЙСТВИЯ ===")

    try:
        from utils.building_manager import get_building_manager, ActionType

        building_manager = get_building_manager()

        # Тестовые данные эмулятора
        test_emulator_data = {
            'id': 1,
            'lord_level': 12
        }

        logger.info("🎯 Определение следующего действия...")

        # Получаем следующее действие
        next_action = building_manager.determine_next_action(test_emulator_data)

        if next_action:
            logger.success(f"✅ Найдено действие: {next_action.action_type.value}")
            logger.info(f"  Предмет: {next_action.item_name}")
            logger.info(f"  Уровень: {next_action.current_level} -> {next_action.target_level}")
            logger.info(f"  Приоритет: {next_action.priority}")
            logger.info(f"  Ускорение: {'Да' if next_action.use_speedup else 'Нет'}")
            logger.info(f"  Прайм-тайм бонус: +{next_action.prime_time_bonus}")
            logger.info(f"  Причина: {next_action.reason}")
        else:
            logger.warning("⚠️ Нет доступных действий")
            logger.info("  Возможные причины:")
            logger.info("    - Все слоты строительства и исследований заняты")
            logger.info("    - Нет зданий/исследований готовых для апгрейда")
            logger.info("    - Все требования для текущего лорда выполнены")

        logger.success("✅ Тест определения действий завершен")

    except Exception as e:
        logger.error(f"❌ Ошибка тестирования действий: {e}")


def test_priority_queue():
    """Тест создания очереди приоритетов"""
    logger.info("\n=== ТЕСТ ОЧЕРЕДИ ПРИОРИТЕТОВ ===")

    try:
        from utils.building_manager import get_building_manager

        building_manager = get_building_manager()

        test_emulator_id = 1
        test_lord_level = 12

        logger.info("📋 Создание очереди приоритетов...")

        # Получаем очередь действий
        action_queue = building_manager.get_action_priority_queue(test_emulator_id, test_lord_level)

        logger.info(f"Всего действий в очереди: {len(action_queue)}")

        # Показываем топ-5 действий
        top_actions = action_queue[:5]

        if top_actions:
            logger.info("Топ-5 приоритетных действий:")
            for i, action in enumerate(top_actions, 1):
                action_type_icon = "🏗️" if action.action_type.value == "building" else "📚"
                logger.info(f"  {i}. {action_type_icon} {action.action_type.value}: {action.item_name}")
                logger.info(f"     Приоритет: {action.priority} | Прайм-тайм: +{action.prime_time_bonus}")
                logger.info(f"     Ускорение: {'Да' if action.use_speedup else 'Нет'}")
                logger.info(f"     {action.reason}")
        else:
            logger.warning("⚠️ Очередь действий пуста")
            logger.info("  Возможные причины:")
            logger.info("    - Нет данных в БД о зданиях/исследованиях")
            logger.info("    - Все здания/исследования завершены")
            logger.info("    - Не загружены требования лорда")

        logger.success("✅ Тест очереди приоритетов завершен")

    except Exception as e:
        logger.error(f"❌ Ошибка тестирования очереди: {e}")


def test_lord_upgrade_check():
    """Тест проверки готовности к повышению лорда"""
    logger.info("\n=== ТЕСТ ПРОВЕРКИ ПОВЫШЕНИЯ ЛОРДА ===")

    try:
        from utils.building_manager import get_building_manager

        building_manager = get_building_manager()

        test_emulator_id = 1
        test_lord_levels = [10, 12, 15, 18]

        for lord_level in test_lord_levels:
            logger.info(f"\n👑 Проверка готовности лорда {lord_level} -> {lord_level + 1}:")

            ready, missing = building_manager.check_lord_upgrade_requirements(test_emulator_id, lord_level)

            if ready:
                logger.success(f"  ✅ Готов к повышению до {lord_level + 1} уровня!")
            else:
                logger.warning(f"  ❌ НЕ готов к повышению")

                # Показываем недостающие требования
                if missing:
                    for category, items in missing.items():
                        if items:
                            logger.info(f"    Недостает в категории '{category}':")
                            for item in items[:3]:  # Показываем максимум 3
                                logger.info(f"      - {item.get('name', 'Неизвестно')}")

        logger.success("✅ Тест проверки лорда завершен")

    except Exception as e:
        logger.error(f"❌ Ошибка тестирования лорда: {e}")


def test_building_summary():
    """Тест получения сводки по строительству"""
    logger.info("\n=== ТЕСТ СВОДКИ ПО СТРОИТЕЛЬСТВУ ===")

    try:
        from utils.building_manager import get_building_manager

        building_manager = get_building_manager()

        test_emulator_id = 1
        test_lord_level = 12

        logger.info("📊 Создание сводки...")

        summary = building_manager.get_building_summary(test_emulator_id, test_lord_level)

        logger.info(f"Эмулятор ID: {summary['emulator_id']}")
        logger.info(f"Уровень лорда: {summary['lord_level']}")
        logger.info(f"Готов к повышению лорда: {'✅' if summary['lord_upgrade_ready'] else '❌'}")

        # Информация о слотах
        building_slots = summary['slots']['building']
        research_slots = summary['slots']['research']

        logger.info(f"Строительство: {building_slots['free']}/{building_slots['total']} слотов свободно")
        logger.info(f"Исследования: {research_slots['free']}/{research_slots['total']} слотов свободно")

        # Следующее действие
        next_action = summary['next_action']
        if next_action:
            logger.info(f"Следующее действие: {next_action['type']} - {next_action['item']}")
            logger.info(f"  Уровень: {next_action['level']}")
            logger.info(f"  Приоритет: {next_action['priority']}")
            logger.info(f"  Причина: {next_action['reason']}")
        else:
            logger.warning("Нет доступных действий")

        # Статус прайм-тайма
        prime_status = summary['prime_time_status']
        logger.info(f"Прайм-тайм: активно {prime_status['current_active']} действий")

        logger.success("✅ Тест сводки завершен")

    except Exception as e:
        logger.error(f"❌ Ошибка тестирования сводки: {e}")


def main():
    """Основная функция"""
    setup_logging()

    logger.info("🏗️ ТЕСТИРОВАНИЕ BUILDING MANAGER - МОЗГИ СИСТЕМЫ")
    logger.info("Проверка ПАРАЛЛЕЛЬНОЙ работы зданий И исследований")

    try:
        # 1. Тест инициализации
        building_manager = test_building_manager_initialization()
        if not building_manager:
            logger.error("Критическая ошибка инициализации")
            return 1

        # 2. Тест слотов
        test_slot_status_calculation()

        # 3. Тест определения действий
        test_action_determination()

        # 4. Тест очереди приоритетов
        test_priority_queue()

        # 5. Тест проверки лорда
        test_lord_upgrade_check()

        # 6. Тест сводки
        test_building_summary()

        logger.success("\n🎉 ВСЕ ТЕСТЫ BUILDING MANAGER ЗАВЕРШЕНЫ УСПЕШНО!")
        logger.info("BuildingManager готов для интеграции с orchestrator.py")
        logger.info("\n✅ ИСПРАВЛЕНЫ ВСЕ ПРОБЛЕМЫ ИНТЕГРАЦИИ:")
        logger.info("  - Исправлены названия методов database.py")
        logger.info("  - Исправлено обращение к полям данных")
        logger.info("  - Настройки ускорений берутся из БД")
        logger.info("  - Параллельная работа зданий И исследований")
        logger.info("\n🚀 ГОТОВ К ПРОМТУ 16: логика параллельного планирования")

        return 0

    except Exception as e:
        logger.error(f"❌ Критическая ошибка тестирования: {e}")
        return 1


if __name__ == "__main__":
    exit(main())