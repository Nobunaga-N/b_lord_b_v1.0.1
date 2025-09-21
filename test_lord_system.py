"""
Тестовый скрипт для проверки системы управления требованиями лорда.
Демонстрирует загрузку конфига и работу с требованиями.
"""

import sys
from pathlib import Path

# Добавляем корневую папку в путь для импорта модулей
sys.path.append(str(Path(__file__).parent))

from loguru import logger
from utils.database import Database


def setup_logging():
    """Настройка логирования для тестов"""
    logger.remove()
    logger.add(
        sys.stdout,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
        level="INFO"
    )


def test_lord_requirements_system():
    """Тестирование системы требований лорда"""

    logger.info("=== ТЕСТ СИСТЕМЫ ТРЕБОВАНИЙ ЛОРДА ===")

    # Инициализируем БД
    db = Database("data/test_beast_lord.db")

    # 1. Загружаем требования из конфига
    logger.info("\n1. Загрузка требований из building_chains.yaml...")
    if db.load_lord_requirements_from_config():
        logger.success("✅ Требования загружены успешно")
    else:
        logger.error("❌ Ошибка загрузки требований")
        return False

    # 2. Создаем тестового эмулятора
    logger.info("\n2. Создание тестового эмулятора...")
    emulator_id = db.sync_emulator(
        emulator_index=0,
        emulator_name="Test Emulator",
        enabled=True,
        notes="Тестовый эмулятор для проверки системы"
    )
    logger.success(f"✅ Создан эмулятор с ID: {emulator_id}")

    # 3. Инициализируем прогресс из конфига
    logger.info("\n3. Инициализация прогресса из конфига...")
    if db.init_emulator_from_config(emulator_id):
        logger.success("✅ Прогресс инициализирован")
    else:
        logger.error("❌ Ошибка инициализации прогресса")
        return False

    # 4. Проверяем требования для лорда 11
    logger.info("\n4. Проверка требований для лорда 11...")
    requirements = db.get_lord_requirements(11)

    if requirements:
        logger.info(f"Найдены требования для лорда 11:")
        for category, items in requirements.items():
            logger.info(f"  {category.upper()}:")
            for name, level in items.items():
                logger.info(f"    - {name}: {level}")
    else:
        logger.warning("Требования для лорда 11 не найдены")

    # 5. Симулируем некоторый прогресс
    logger.info("\n5. Симуляция прогресса строительства...")

    # Улучшаем несколько зданий
    test_buildings = [
        ("улей", 8),
        ("ферма_грунта", 10),
        ("склад_песка", 7),
        ("голово_всеядных", 9)
    ]

    for building_name, level in test_buildings:
        db.update_building_progress(emulator_id, building_name, current_level=level)
        logger.info(f"  - {building_name}: уровень {level}")

    # 6. Проверяем готовность к повышению лорда
    logger.info("\n6. Проверка готовности к повышению лорда 11...")
    ready, missing = db.check_lord_upgrade_readiness(emulator_id, 11)

    if ready:
        logger.success("✅ Готов к повышению лорда до 11 уровня!")
    else:
        logger.warning("❌ Не готов к повышению лорда 11")
        logger.info("Недостающие требования:")
        for category, items in missing.items():
            if items:
                logger.info(f"  {category.upper()}:")
                for item in items:
                    logger.info(f"    - {item}")

    # 7. Получаем недостающие требования
    logger.info("\n7. Детальный анализ недостающих требований...")
    missing_detailed = db.get_missing_requirements(emulator_id, 11)

    for category, items in missing_detailed.items():
        if items:
            logger.info(f"{category.upper()} (недостает {len(items)} элементов):")
            for item in items:
                logger.info(f"  - {item['name']}: {item['current_level']}/{item['required_level']} "
                            f"(нужно +{item['levels_needed']})")

    # 8. Определяем следующее здание для апгрейда
    logger.info("\n8. Определение следующего здания для апгрейда...")
    next_building = db.get_next_building_to_upgrade(emulator_id, 10)  # Текущий лорд 10

    if next_building:
        logger.success(f"✅ Следующее для апгрейда: {next_building['name']}")
        logger.info(f"  Тип: {next_building['type']}")
        logger.info(f"  Текущий уровень: {next_building['current_level']}")
        logger.info(f"  Целевой уровень: {next_building['target_level']}")
        logger.info(f"  Финальная цель: {next_building['final_target']}")
        logger.info(f"  Для лорда: {next_building['lord_level']}")
    else:
        logger.info("Нет зданий/исследований готовых для апгрейда")

    # 9. Обновляем цели на основе уровня лорда
    logger.info("\n9. Обновление целей для лорда 11...")
    if db.update_building_targets_for_lord_level(emulator_id, 11):
        logger.success("✅ Цели зданий обновлены")

    if db.update_research_targets_for_lord_level(emulator_id, 11):
        logger.success("✅ Цели исследований обновлены")

    # 10. Получаем прогресс для лорда 11
    logger.info("\n10. Анализ прогресса для лорда 11...")
    progress = db.get_building_progress_for_lord(emulator_id, 11)

    if progress:
        logger.info(f"Прогресс зданий для лорда 11:")
        logger.info(f"  Всего зданий: {progress['total_buildings']}")
        logger.info(f"  Завершено: {progress['completed_buildings']}")
        logger.info(f"  В процессе: {progress['buildings_in_progress']}")
        logger.info(f"  Готово к апгрейду: {progress['buildings_ready']}")

        # Показываем первые 5 зданий для примера
        logger.info("  Детали (первые 5 зданий):")
        for building in progress['buildings_details'][:5]:
            status_icon = {"completed": "✅", "in_progress": "🔄", "ready": "⏳", "not_initialized": "❌"}
            icon = status_icon.get(building['status'], "❓")
            logger.info(f"    {icon} {building['building_name']}: "
                        f"{building.get('current_level', 0)}/{building['required_level']}")

    # 11. Статистика БД
    logger.info("\n11. Статистика базы данных:")
    stats = db.get_database_stats()
    for table, count in stats.items():
        logger.info(f"  {table}: {count} записей")

    logger.success("\n=== ТЕСТ ЗАВЕРШЕН УСПЕШНО ===")
    return True


def main():
    """Основная функция"""
    setup_logging()

    try:
        # Проверяем наличие конфига
        config_path = Path("configs/building_chains.yaml")
        if not config_path.exists():
            logger.error(f"Файл конфигурации не найден: {config_path}")
            logger.info("Создайте файл configs/building_chains.yaml перед запуском теста")
            return 1

        # Запускаем тест
        if test_lord_requirements_system():
            logger.success("Все тесты прошли успешно! 🎉")
            return 0
        else:
            logger.error("Некоторые тесты завершились с ошибкой")
            return 1

    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        return 1


if __name__ == "__main__":
    exit(main())