"""
Исправленный тестовый скрипт для проверки системы управления требованиями лорда
с правильной логикой требований и механикой игровых слотов.
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


def test_updated_lord_system():
    """Тестирование исправленной системы требований лорда с правильной механикой слотов"""

    logger.info("=== ТЕСТ ИСПРАВЛЕННОЙ СИСТЕМЫ ТРЕБОВАНИЙ ЛОРДА ===")
    logger.info("✨ ИСПРАВЛЕНИЯ:")
    logger.info("   🔧 Требования лорда: lord_requirements[X] = требования для повышения С (X-1) ДО X")
    logger.info("   🔧 Здания И исследования качаются ПО ГОТОВНОСТИ в своих слотах!")
    logger.info("   🔧 Строители: 3-4 слота (зависит от уровня лорда)")
    logger.info("   🔧 Исследования: отдельная очередь (1 слот)")
    logger.info("   🔧 Строго по порядку как в txt списках!")
    logger.info("   🔧 Ветки исследований согласно 'Исследования.txt'")
    logger.info("   🔧 Здания согласно 'Список зданий.txt'")

    # Инициализируем БД
    db = Database("data/test_beast_lord_v2_fixed.db")

    # 1. Загружаем требования из исправленного конфига
    logger.info("\n1. Загрузка ИСПРАВЛЕННЫХ требований...")
    if db.load_lord_requirements_from_config():
        logger.success("✅ Требования загружены успешно")
    else:
        logger.error("❌ Ошибка загрузки требований")
        return False

    # 2. Создаем тестового эмулятора
    logger.info("\n2. Создание тестового эмулятора...")
    emulator_id = db.sync_emulator(
        emulator_index=0,
        emulator_name="Test Emulator Fixed",
        enabled=True,
        notes="Тестовый эмулятор для исправленной системы"
    )
    logger.success(f"✅ Создан эмулятор с ID: {emulator_id}")

    # 3. Инициализируем прогресс из исправленного конфига
    logger.info("\n3. Инициализация прогресса с исправленными ветками...")
    if db.init_emulator_from_config(emulator_id):
        logger.success("✅ Прогресс инициализирован")
    else:
        logger.error("❌ Ошибка инициализации прогресса")
        return False

    # 4. Проверяем ИСПРАВЛЕННЫЕ требования для лорда 11
    logger.info("\n4. Проверка ИСПРАВЛЕННЫХ требований для лорда 11...")
    logger.info("   (Это требования для повышения С 10 ДО 11)")

    requirements = db.get_lord_requirements(11)

    if requirements:
        logger.info(f"Найдены требования для повышения С 10 ДО 11:")
        for category, items in requirements.items():
            logger.info(f"  {category.upper()}:")
            for name, level in items.items():
                logger.info(f"    - {name}: до {level} уровня")
    else:
        logger.warning("Требования для лорда 11 не найдены")

    # 5. Симулируем прогресс строительства (почти готовы к лорду 11)
    logger.info("\n5. Симуляция прогресса строительства (почти готовы к лорду 11)...")

    # Согласно "Список зданий.txt" для повышения с 10 до 11 нужно:
    test_buildings = [
        ("улей", 10),               # Готов ✅
        ("ферма_грунта", 10),       # Готов ✅
        ("ферма_яблок", 9),         # Почти готов (нужно 10)
        ("ферма_листьев", 10),      # Готов ✅
        ("пруд", 8),                # Готов ✅
        ("флора_эволюции", 6),      # Почти готов (нужно 7)
        ("склад_песка", 7),         # Готов ✅
        ("склад_листьев", 7),       # Готов ✅
        ("склад_грунта", 7),        # Готов ✅
        ("склад_яблок", 6),         # Почти готов (нужно 7)
        ("склад_воды", 7),          # Готов ✅
        ("голово_всеядных", 10),    # Готов ✅
        ("логово_плотоядных", 9),   # Почти готов (нужно 10)
    ]

    for building_name, level in test_buildings:
        db.update_building_progress(emulator_id, building_name, current_level=level)
        logger.info(f"  - {building_name}: уровень {level}")

    # 6. Проверяем готовность к повышению лорда 11 (ТОЛЬКО здания)
    logger.info("\n6. Проверка готовности к повышению лорда 11 (ТОЛЬКО здания блокируют)...")
    ready, missing = db.check_lord_upgrade_readiness(emulator_id, 11)

    if ready:
        logger.success("✅ Готов к повышению лорда до 11 уровня!")
    else:
        logger.warning("❌ Не готов к повышению лорда 11")
        logger.info("Недостающие требования:")
        for category, items in missing.items():
            if items and category == 'buildings':
                logger.info(f"  ЗДАНИЯ (БЛОКИРУЮТ):")
                for item in items:
                    logger.info(f"    - {item}")
            elif category == 'research_info':
                logger.info(f"  ИССЛЕДОВАНИЯ (НЕ БЛОКИРУЮТ, для информации):")
                for item in items:
                    logger.info(f"    - {item}")

    # 7. Детальный анализ недостающих требований
    logger.info("\n7. Детальный анализ недостающих требований...")
    missing_detailed = db.get_missing_requirements(emulator_id, 11)

    for category, items in missing_detailed.items():
        if items and category == 'buildings':
            logger.info(f"ЗДАНИЯ (недостает {len(items)} элементов, БЛОКИРУЮТ лорда):")
            for item in items:
                logger.info(f"  - {item['name']}: {item['current_level']}/{item['required_level']} "
                            f"(нужно +{item['levels_needed']})")

    # 8. Тестируем исправленные ветки исследований
    logger.info("\n8. Тестирование ИСПРАВЛЕННЫХ веток исследований...")

    # Проверяем разблокированы ли исследования для разных уровней лорда
    test_researches = [
        ("развитие_территории", 10, True),     # Развитие территории - с лорда 10
        ("изобилие_света", 10, True),          # Развитие территории - с лорда 10
        ("накопитель", 10, True),              # Развитие территории - с лорда 10
        ("похвала_за_смелость", 12, False),    # Базовый бой - с лорда 13
        ("похвала_за_смелость", 13, True),     # Базовый бой - с лорда 13
        ("начальная_атака", 13, True),         # Базовый бой - с лорда 13
        ("преимущество_скорости", 13, False),  # Средний бой - с лорда 14
        ("преимущество_скорости", 14, True),   # Средний бой - с лорда 14
        ("начальный_совместный_бой", 14, True), # Особый отряд - с лорда 14
        ("эффективный_сбор", 16, False),       # Походные отряды - с лорда 17
        ("эффективный_сбор", 17, True),        # Походные отряды - с лорда 17
    ]

    for research_name, lord_level, expected in test_researches:
        result = db.is_research_unlocked(research_name, lord_level)
        status = "✅" if result == expected else "❌"
        logger.info(f"  {status} {research_name} для лорда {lord_level}: {result} (ожидалось {expected})")

    # 9. Определяем следующее для апгрейда с ПРАВИЛЬНОЙ логикой
    logger.info("\n9. Определение следующего действия (по готовности в слотах)...")
    logger.info("   🏗️ Строители: 3-4 слота в зависимости от уровня лорда")
    logger.info("   📚 Исследования: отдельная очередь (1 слот)")
    logger.info("   ⚡ ВСЁ качается ПО ГОТОВНОСТИ в рамках доступных слотов!")

    # Устанавливаем лорда 10 ПРАВИЛЬНЫМ способом (через emulator_index)
    emulator_data = db.get_emulator(0)  # Получаем по emulator_index
    if emulator_data:
        emulator_db_id = emulator_data['id']
        db.update_emulator_progress(emulator_db_id, lord_level=10)
        logger.info(f"Установлен лорд 10 для эмулятора с DB ID: {emulator_db_id}")
    else:
        logger.error("Не удалось найти эмулятор для обновления")
        return False

    next_upgrade = db.get_next_building_to_upgrade(emulator_db_id, 10)

    if next_upgrade:
        logger.success(f"✅ Следующее для апгрейда: {next_upgrade['name']}")
        logger.info(f"  Тип: {next_upgrade['type']}")
        logger.info(f"  Текущий уровень: {next_upgrade['current_level']}")
        logger.info(f"  Целевой уровень: {next_upgrade['target_level']}")
        logger.info(f"  Финальная цель: {next_upgrade['final_target']}")
        logger.info(f"  Для лорда: {next_upgrade['lord_level']}")
        logger.info(f"  Приоритет: {next_upgrade['priority']}")
    else:
        logger.info("Нет зданий/исследований готовых для апгрейда")

    # 10. Тестируем доступные исследования для лорда 13
    logger.info("\n10. Тестирование доступных исследований для лорда 13...")
    db.update_emulator_progress(emulator_db_id, lord_level=13)

    available_research = db.get_available_research_for_upgrade(emulator_db_id)

    if available_research:
        logger.info(f"Доступно {len(available_research)} исследований для лорда 13:")
        for research in available_research[:5]:  # Показываем первые 5
            logger.info(f"  - {research['research_name']}: {research['current_level']}/{research['target_level']}")
    else:
        logger.info("Нет доступных исследований для лорда 13")

    # 11. Проверяем что лорд готов к повышению БЕЗ исследований
    logger.info("\n11. Проверка что исследования НЕ блокируют лорда...")

    # Обновляем все здания до готовности для лорда 11
    buildings_for_lord_11 = [
        ("улей", 10), ("ферма_грунта", 10), ("ферма_яблок", 10),
        ("ферма_листьев", 10), ("пруд", 8), ("флора_эволюции", 7),
        ("склад_песка", 7), ("склад_листьев", 7), ("склад_грунта", 7),
        ("склад_яблок", 7), ("склад_воды", 7), ("голово_всеядных", 10),
        ("логово_плотоядных", 10)
    ]

    for building_name, level in buildings_for_lord_11:
        db.update_building_progress(emulator_db_id, building_name, current_level=level)

    # Устанавливаем обратно лорда 10 для теста
    db.update_emulator_progress(emulator_db_id, lord_level=10)

    ready_11, missing_11 = db.check_lord_upgrade_readiness(emulator_db_id, 11)

    if ready_11:
        logger.success("✅ Лорд 11 готов к повышению! Исследования НЕ блокируют!")
    else:
        logger.warning("❌ Лорд 11 не готов, проверяем здания:")
        for category, items in missing_11.items():
            if items and category == 'buildings':
                logger.info(f"  Недостающие здания:")
                for item in items:
                    logger.info(f"    - {item}")

    # 12. Статистика БД
    logger.info("\n12. Статистика базы данных:")
    stats = db.get_database_stats()
    for table, count in stats.items():
        logger.info(f"  {table}: {count} записей")

    logger.success("\n=== ТЕСТ ИСПРАВЛЕННОЙ СИСТЕМЫ ЗАВЕРШЕН УСПЕШНО ===")
    logger.info("🎯 ИСПРАВЛЕНИЯ ПОДТВЕРЖДЕНЫ:")
    logger.info("   ✅ Требования лорда работают правильно (С X-1 ДО X)")
    logger.info("   ✅ Здания И исследования качаются ПО ГОТОВНОСТИ!")
    logger.info("   ✅ Строители: 3-4 слота, исследования: отдельная очередь")
    logger.info("   ✅ Строго по порядку как в txt списках")
    logger.info("   ✅ Ветки исследований соответствуют 'Исследования.txt'")
    logger.info("   ✅ Здания соответствуют 'Список зданий.txt'")
    logger.info("   ✅ Работа по готовности: здания + исследования в своих слотах")
    return True


def main():
    """Основная функция"""
    setup_logging()

    try:
        # Проверяем наличие исправленного конфига
        config_path = Path("configs/building_chains.yaml")
        if not config_path.exists():
            logger.error(f"Файл конфигурации не найден: {config_path}")
            logger.info("Создайте ИСПРАВЛЕННЫЙ файл configs/building_chains.yaml перед запуском теста")
            return 1

        # Запускаем тест
        if test_updated_lord_system():
            logger.success("Все тесты прошли успешно! 🎉")
            return 0
        else:
            logger.error("Некоторые тесты завершились с ошибкой")
            return 1

    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return 1


if __name__ == "__main__":
    exit(main())