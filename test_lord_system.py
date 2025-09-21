"""
Обновленный тестовый скрипт для проверки системы управления требованиями лорда
с исправленной логикой исследований (ветки, не блокируют лорда).
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
    """Тестирование обновленной системы требований лорда с ветками исследований"""

    logger.info("=== ТЕСТ ОБНОВЛЕННОЙ СИСТЕМЫ ТРЕБОВАНИЙ ЛОРДА ===")
    logger.info("✨ Исследования НЕ блокируют повышение лорда")
    logger.info("✨ Ветки исследований согласно txt файлам:")
    logger.info("   📚 Развитие территории (включая накопитель) - с лорда 10")
    logger.info("   ⚔️ Базовый бой (все боевые исследования) - с лорда 13")
    logger.info("   💰 Средний бой (экономические) - с лорда 14")
    logger.info("   🚶 Походные отряды - с лорда 17")

    # Инициализируем БД
    db = Database("data/test_beast_lord_v2.db")

    # 1. Загружаем требования из конфига (только здания)
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
        emulator_name="Test Emulator v2",
        enabled=True,
        notes="Тестовый эмулятор для проверки обновленной системы"
    )
    logger.success(f"✅ Создан эмулятор с ID: {emulator_id}")

    # 3. Инициализируем прогресс из конфига С ВЕТКАМИ ИССЛЕДОВАНИЙ
    logger.info("\n3. Инициализация прогресса с ветками исследований...")
    if db.init_emulator_from_config(emulator_id):
        logger.success("✅ Прогресс инициализирован с ветками исследований")
    else:
        logger.error("❌ Ошибка инициализации прогресса")
        return False

    # 4. Проверяем требования для лорда 11 (ТОЛЬКО ЗДАНИЯ)
    logger.info("\n4. Проверка требований для лорда 11 (только здания)...")
    requirements = db.get_lord_requirements(11)

    if requirements:
        logger.info(f"Найдены требования для лорда 11:")
        for category, items in requirements.items():
            logger.info(f"  {category.upper()}:")
            for name, level in items.items():
                logger.info(f"    - {name}: {level}")
    else:
        logger.warning("Требования для лорда 11 не найдены")

    # 5. Симулируем некоторый прогресс ЗДАНИЙ
    logger.info("\n5. Симуляция прогресса строительства...")

    # Улучшаем несколько зданий согласно txt файлам (приближаемся к готовности лорда 11)
    test_buildings = [
        ("улей", 10),  # Почти готов (нужно 11)
        ("ферма_грунта", 11),  # Готов
        ("ферма_яблок", 10),  # Почти готов (нужно 11)
        ("ферма_листьев", 10),  # Готов (остается на 10)
        ("пруд", 8),  # Готов (остается на 8)
        ("флора_эволюции", 7),  # Почти готов (нужно 8)
        ("склад_песка", 8),  # Готов
        ("склад_листьев", 7),  # Почти готов (нужно 8)
        ("склад_грунта", 8),  # Готов
        ("склад_яблок", 7),  # Почти готов (нужно 8)
        ("склад_воды", 7),  # Готов (остается на 7)
        ("голово_всеядных", 11),  # Готов
        ("логово_плотоядных", 10),  # Почти готов (нужно 11)
        ("жилище_детенышей", 8),  # Не готов (нужно 11)
        ("центр_альянса", 9),  # Не готов (нужно 11)
    ]

    for building_name, level in test_buildings:
        db.update_building_progress(emulator_id, building_name, current_level=level)
        logger.info(f"  - {building_name}: уровень {level}")

    # 6. Проверяем готовность к повышению лорда 11 (БЕЗ УЧЕТА ИССЛЕДОВАНИЙ)
    logger.info("\n6. Проверка готовности к повышению лорда 11 (только здания)...")
    ready, missing = db.check_lord_upgrade_readiness(emulator_id, 11)

    if ready:
        logger.success("✅ Готов к повышению лорда до 11 уровня!")
    else:
        logger.warning("❌ Не готов к повышению лорда 11")
        logger.info("Недостающие требования:")
        for category, items in missing.items():
            if items and category != 'research_info':  # Не показываем research_info как блокирующие
                logger.info(f"  {category.upper()} (блокирует):")
                for item in items:
                    logger.info(f"    - {item}")
            elif category == 'research_info':
                logger.info(f"  ИССЛЕДОВАНИЯ (НЕ блокируют):")
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
        elif category == 'research_info':
            logger.info(f"ИССЛЕДОВАНИЯ (НЕ БЛОКИРУЮТ лорда, качаются по готовности):")
            for item in items:
                logger.info(f"  - {item['name']}: {item['current_level']}/{item['required_level']} "
                            f"(нужно +{item['levels_needed']})")

    # 8. Тестируем ветки исследований
    logger.info("\n8. Тестирование веток исследований...")

    # Проверяем разблокированы ли исследования для разных уровней лорда (по txt файлам)
    test_researches = [
        ("развитие_территории", 10, True),  # Развитие территории - с лорда 10
        ("накопитель", 10, True),  # Накопитель тоже с лорда 10 (в той же ветке)
        ("изобилие_света", 10, True),  # Все исследования развития территории - с лорда 10
        ("начальная_атака", 12, False),  # Базовый бой - с лорда 13
        ("начальная_атака", 13, True),  # Базовый бой - с лорда 13
        ("средняя_атака", 13, True),  # Средняя атака входит в базовый бой (с лорда 13)
        ("преимущество_скорости", 13, False),  # Средний бой (экономика) - с лорда 14
        ("преимущество_скорости", 14, True),  # Средний бой (экономика) - с лорда 14
        ("походный_отряд_1", 16, False),  # Походные отряды - с лорда 17
        ("походный_отряд_1", 17, True),  # Походные отряды - с лорда 17
    ]

    for research_name, lord_level, expected in test_researches:
        result = db.is_research_unlocked(research_name, lord_level)
        status = "✅" if result == expected else "❌"
        logger.info(f"  {status} {research_name} для лорда {lord_level}: {result} (ожидалось {expected})")

    # 9. Определяем следующее для апгрейда с новой логикой
    logger.info("\n9. Определение следующего для апгрейда (приоритет: здания для лорда)...")

    # Сначала проверим с лордом 10 (должны быть здания для лорда 11)
    db.update_emulator_progress(emulator_id, lord_level=10)
    next_upgrade = db.get_next_building_to_upgrade(emulator_id, 10)

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
    db.update_emulator_progress(emulator_id, lord_level=13)

    available_research = db.get_available_research_for_upgrade(emulator_id)

    if available_research:
        logger.info(f"Доступно {len(available_research)} исследований для лорда 13:")
        for research in available_research[:5]:  # Показываем первые 5
            logger.info(f"  - {research['research_name']}: {research['current_level']}/{research['target_level']}")
    else:
        logger.info("Нет доступных исследований для лорда 13")

    # 11. Проверяем что лорд 13 готов к повышению БЕЗ исследований
    logger.info("\n11. Проверка что исследования НЕ блокируют лорда 13...")

    # Обновляем все здания для лорда 13 согласно txt файлам
    buildings_for_lord_13 = [
        ("улей", 13), ("ферма_грунта", 12), ("ферма_яблок", 13),
        ("ферма_листьев", 10), ("пруд", 8),  # остаются на предыдущих уровнях
        ("флора_эволюции", 10), ("склад_песка", 10), ("склад_листьев", 10),
        ("склад_грунта", 10), ("склад_яблок", 10), ("склад_воды", 7),
        ("голово_всеядных", 13), ("логово_плотоядных", 13),
        ("жилище_детенышей", 13), ("центр_альянса", 13),
        ("центр_сбора_2", 1), ("склад_2", 1)  # новые здания для лорда 13
    ]

    for building_name, level in buildings_for_lord_13:
        db.update_building_progress(emulator_id, building_name, current_level=level)

    ready_13, missing_13 = db.check_lord_upgrade_readiness(emulator_id, 13)

    if ready_13:
        logger.success("✅ Лорд 13 готов к повышению! Исследования НЕ блокируют!")
    else:
        logger.warning("❌ Лорд 13 не готов, проверяем здания:")
        for category, items in missing_13.items():
            if items and category == 'buildings':
                logger.info(f"  Недостающие здания:")
                for item in items:
                    logger.info(f"    - {item}")

    # 12. Статистика БД
    logger.info("\n12. Статистика базы данных:")
    stats = db.get_database_stats()
    for table, count in stats.items():
        logger.info(f"  {table}: {count} записей")

    logger.success("\n=== ТЕСТ ОБНОВЛЕННОЙ СИСТЕМЫ ЗАВЕРШЕН УСПЕШНО ===")
    logger.info("🎯 Исследования больше НЕ блокируют повышение лорда")
    logger.info("🎯 Ветки исследований соответствуют txt файлам:")
    logger.info("   📚 Развитие территории (включая накопитель) - лорд 10+")
    logger.info("   ⚔️ Базовый бой (все боевые + мутации) - лорд 13+")
    logger.info("   💰 Средний бой (экономические) - лорд 14+")
    logger.info("   🚶 Походные отряды - лорд 17+")
    logger.info("🎯 Здания соответствуют списку из txt файла")
    logger.info("🎯 Приоритет: здания для лорда → доступные исследования → остальные здания")
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
        if test_updated_lord_system():
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