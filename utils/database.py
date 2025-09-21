"""
Система управления базой данных для Beast Lord Bot.
Содержит детальный прогресс строительства, исследований и игровых сессий.
"""

import sqlite3
import json
import yaml
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from pathlib import Path
from contextlib import contextmanager

from loguru import logger


class Database:
    """Класс для управления базой данных бота"""

    def __init__(self, db_path: str = "data/beast_lord.db"):
        """
        Инициализация базы данных

        Args:
            db_path: Путь к файлу базы данных
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info(f"Инициализирована база данных: {self.db_path}")
        self._init_database()

    def _init_database(self) -> None:
        """Инициализация структуры базы данных"""
        logger.info("Создаем структуру базы данных...")

        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Основная таблица эмуляторов
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS emulators (
                    id INTEGER PRIMARY KEY,
                    emulator_name TEXT UNIQUE NOT NULL,
                    emulator_index INTEGER UNIQUE NOT NULL,
                    enabled BOOLEAN DEFAULT FALSE,
                    notes TEXT DEFAULT '',

                    -- Игровой прогресс
                    lord_level INTEGER DEFAULT 10,
                    last_processed TIMESTAMP,
                    next_check_time TIMESTAMP,
                    priority_score INTEGER DEFAULT 0,

                    -- Состояния
                    ready_for_lord_upgrade BOOLEAN DEFAULT FALSE,
                    waiting_for_prime_time BOOLEAN DEFAULT FALSE,
                    next_prime_time_window TIMESTAMP,

                    -- Метаданные
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Детальный прогресс строительства
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS building_progress (
                    id INTEGER PRIMARY KEY,
                    emulator_id INTEGER NOT NULL,
                    building_name TEXT NOT NULL,
                    current_level INTEGER DEFAULT 0,
                    target_level INTEGER NOT NULL,
                    use_speedups BOOLEAN DEFAULT FALSE,

                    -- Текущее строительство
                    is_building BOOLEAN DEFAULT FALSE,
                    build_start_time TIMESTAMP,
                    estimated_completion TIMESTAMP,

                    -- Метаданные
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                    FOREIGN KEY (emulator_id) REFERENCES emulators(id) ON DELETE CASCADE,
                    UNIQUE(emulator_id, building_name)
                )
            ''')

            # Детальный прогресс исследований
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS research_progress (
                    id INTEGER PRIMARY KEY,
                    emulator_id INTEGER NOT NULL,
                    research_name TEXT NOT NULL,
                    current_level INTEGER DEFAULT 0,
                    target_level INTEGER NOT NULL,
                    use_speedups BOOLEAN DEFAULT FALSE,

                    -- Текущее исследование
                    is_researching BOOLEAN DEFAULT FALSE,
                    research_start_time TIMESTAMP,
                    estimated_completion TIMESTAMP,

                    -- Метаданные
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                    FOREIGN KEY (emulator_id) REFERENCES emulators(id) ON DELETE CASCADE,
                    UNIQUE(emulator_id, research_name)
                )
            ''')

            # Таблица требований по уровням лорда
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS lord_requirements (
                    id INTEGER PRIMARY KEY,
                    lord_level INTEGER NOT NULL,
                    building_name TEXT NOT NULL,
                    required_level INTEGER NOT NULL,
                    category TEXT NOT NULL DEFAULT 'building',

                    UNIQUE(lord_level, building_name, category)
                )
            ''')

            # Таблица прайм-таймов
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS prime_times (
                    id INTEGER PRIMARY KEY,
                    day_of_week INTEGER NOT NULL,
                    hour INTEGER NOT NULL,
                    minute INTEGER NOT NULL,
                    action_type TEXT NOT NULL,
                    bonus_description TEXT,

                    UNIQUE(day_of_week, hour, minute, action_type)
                )
            ''')

            # Лог игровых сессий
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY,
                    emulator_id INTEGER NOT NULL,
                    start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    end_time TIMESTAMP,
                    success BOOLEAN,
                    actions_completed INTEGER DEFAULT 0,
                    buildings_started INTEGER DEFAULT 0,
                    research_started INTEGER DEFAULT 0,
                    errors TEXT,

                    FOREIGN KEY (emulator_id) REFERENCES emulators(id) ON DELETE CASCADE
                )
            ''')

            # Создаем индексы для оптимизации
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_emulators_index ON emulators(emulator_index)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_emulators_enabled ON emulators(enabled)')
            cursor.execute(
                'CREATE INDEX IF NOT EXISTS idx_building_progress_emulator ON building_progress(emulator_id)')
            cursor.execute(
                'CREATE INDEX IF NOT EXISTS idx_research_progress_emulator ON research_progress(emulator_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_lord_requirements_level ON lord_requirements(lord_level)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_sessions_emulator ON sessions(emulator_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_prime_times_day_hour ON prime_times(day_of_week, hour)')

            conn.commit()

        logger.success("Структура базы данных создана")

    @contextmanager
    def get_connection(self):
        """Контекстный менеджер для работы с подключением к БД"""
        conn = None
        try:
            conn = sqlite3.connect(str(self.db_path), timeout=30.0)
            conn.row_factory = sqlite3.Row  # Возвращать результаты как словари
            conn.execute('PRAGMA foreign_keys = ON')  # Включаем внешние ключи
            yield conn
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"Ошибка базы данных: {e}")
            raise
        finally:
            if conn:
                conn.close()

    # === УПРАВЛЕНИЕ ЭМУЛЯТОРАМИ ===

    def sync_emulator(self, emulator_index: int, emulator_name: str,
                      enabled: bool = False, notes: str = "") -> int:
        """
        Синхронизация эмулятора с БД (создание или обновление)

        Args:
            emulator_index: Индекс эмулятора
            emulator_name: Имя эмулятора
            enabled: Включен ли эмулятор
            notes: Заметки

        Returns:
            ID эмулятора в БД
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Проверяем существует ли эмулятор
            cursor.execute(
                'SELECT id, enabled, notes FROM emulators WHERE emulator_index = ?',
                (emulator_index,)
            )
            existing = cursor.fetchone()

            if existing:
                # Обновляем существующий эмулятор, сохраняя пользовательские настройки
                cursor.execute('''
                    UPDATE emulators 
                    SET emulator_name = ?, 
                        enabled = COALESCE(?, enabled),
                        notes = COALESCE(NULLIF(?, ''), notes),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE emulator_index = ?
                ''', (emulator_name, enabled if enabled else existing['enabled'],
                      notes if notes else existing['notes'], emulator_index))

                emulator_id = existing['id']
                logger.debug(f"Обновлен эмулятор {emulator_index} (ID: {emulator_id})")
            else:
                # Создаем новый эмулятор
                cursor.execute('''
                    INSERT INTO emulators (emulator_index, emulator_name, enabled, notes)
                    VALUES (?, ?, ?, ?)
                ''', (emulator_index, emulator_name, enabled, notes))

                emulator_id = cursor.lastrowid
                logger.info(f"Создан новый эмулятор {emulator_index} (ID: {emulator_id})")

            conn.commit()
            return emulator_id

    def get_emulator(self, emulator_index: int) -> Optional[Dict[str, Any]]:
        """Получение информации об эмуляторе"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM emulators WHERE emulator_index = ?', (emulator_index,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_all_emulators(self, enabled_only: bool = False) -> List[Dict[str, Any]]:
        """Получение списка всех эмуляторов"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            query = 'SELECT * FROM emulators'
            params = []

            if enabled_only:
                query += ' WHERE enabled = TRUE'

            query += ' ORDER BY emulator_index'

            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def update_emulator_progress(self, emulator_index: int, **kwargs) -> bool:
        """Обновление игрового прогресса эмулятора"""
        if not kwargs:
            return True

        # Формируем SET часть запроса
        set_parts = []
        values = []

        for field, value in kwargs.items():
            if field in ['lord_level', 'priority_score', 'ready_for_lord_upgrade',
                         'waiting_for_prime_time', 'last_processed', 'next_check_time',
                         'next_prime_time_window']:
                set_parts.append(f"{field} = ?")
                values.append(value)

        if not set_parts:
            logger.warning(f"Нет допустимых полей для обновления: {list(kwargs.keys())}")
            return False

        set_parts.append("updated_at = CURRENT_TIMESTAMP")
        values.append(emulator_index)

        query = f"UPDATE emulators SET {', '.join(set_parts)} WHERE emulator_index = ?"

        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, values)
                conn.commit()

                if cursor.rowcount > 0:
                    logger.debug(f"Обновлен прогресс эмулятора {emulator_index}: {kwargs}")
                    return True
                else:
                    logger.warning(f"Эмулятор {emulator_index} не найден для обновления")
                    return False

        except Exception as e:
            logger.error(f"Ошибка обновления прогресса эмулятора {emulator_index}: {e}")
            return False

    # === УПРАВЛЕНИЕ ПРОГРЕССОМ СТРОИТЕЛЬСТВА ===

    def init_emulator_from_config(self, emulator_id: int, config_path: str = "configs/building_chains.yaml") -> bool:
        """
        Полная инициализация прогресса эмулятора из конфига

        Args:
            emulator_id: ID эмулятора в БД
            config_path: Путь к файлу конфигурации

        Returns:
            True если инициализация успешна, False иначе
        """
        try:
            config_file = Path(config_path)
            if not config_file.exists():
                logger.error(f"Файл конфигурации не найден: {config_path}")
                return False

            with open(config_file, 'r', encoding='utf-8') as f:
                config_data = yaml.safe_load(f)

            # Инициализируем прогресс зданий
            if 'speedup_settings' in config_data:
                buildings_config = {}
                for building_name, use_speedup in config_data['speedup_settings'].items():
                    buildings_config[building_name] = {
                        'target_level': 1,  # Начальная цель
                        'use_speedups': use_speedup
                    }
                self.init_building_progress(emulator_id, buildings_config)

            # Инициализируем прогресс исследований
            if 'research_speedup_settings' in config_data:
                research_config = {}
                for research_name, use_speedup in config_data['research_speedup_settings'].items():
                    research_config[research_name] = {
                        'target_level': 1,  # Начальная цель
                        'use_speedups': use_speedup
                    }
                self.init_research_progress(emulator_id, research_config)

            logger.success(f"Инициализирован прогресс эмулятора {emulator_id} из конфига")
            return True

        except Exception as e:
            logger.error(f"Ошибка инициализации эмулятора из конфига: {e}")
            return False

    def init_building_progress(self, emulator_id: int, buildings_config: Dict[str, Dict]) -> None:
        """
        Инициализация прогресса строительства для эмулятора

        Args:
            emulator_id: ID эмулятора в БД
            buildings_config: Конфигурация зданий из building_chains.yaml
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()

            for building_name, config in buildings_config.items():
                # Проверяем существует ли запись
                cursor.execute('''
                    SELECT id FROM building_progress 
                    WHERE emulator_id = ? AND building_name = ?
                ''', (emulator_id, building_name))

                if not cursor.fetchone():
                    # Создаем новую запись
                    cursor.execute('''
                        INSERT INTO building_progress 
                        (emulator_id, building_name, target_level, use_speedups)
                        VALUES (?, ?, ?, ?)
                    ''', (
                        emulator_id,
                        building_name,
                        config.get('target_level', 1),
                        config.get('use_speedups', False)
                    ))

            conn.commit()
            logger.info(f"Инициализирован прогресс строительства для эмулятора {emulator_id}")

    def get_building_progress(self, emulator_id: int, building_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """Получение прогресса строительства"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            if building_name:
                cursor.execute('''
                    SELECT * FROM building_progress 
                    WHERE emulator_id = ? AND building_name = ?
                ''', (emulator_id, building_name))
                result = cursor.fetchone()
                return [dict(result)] if result else []
            else:
                cursor.execute('''
                    SELECT * FROM building_progress 
                    WHERE emulator_id = ?
                    ORDER BY building_name
                ''', (emulator_id,))
                return [dict(row) for row in cursor.fetchall()]

    def update_building_progress(self, emulator_id: int, building_name: str, **kwargs) -> bool:
        """Обновление прогресса строительства здания"""
        allowed_fields = [
            'current_level', 'target_level', 'use_speedups',
            'is_building', 'build_start_time', 'estimated_completion'
        ]

        # Фильтруем допустимые поля
        update_data = {k: v for k, v in kwargs.items() if k in allowed_fields}

        if not update_data:
            return True

        # Формируем SET часть запроса
        set_parts = [f"{field} = ?" for field in update_data.keys()]
        set_parts.append("updated_at = CURRENT_TIMESTAMP")

        values = list(update_data.values()) + [emulator_id, building_name]
        query = f'''
            UPDATE building_progress 
            SET {', '.join(set_parts)} 
            WHERE emulator_id = ? AND building_name = ?
        '''

        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, values)
                conn.commit()

                if cursor.rowcount > 0:
                    logger.debug(f"Обновлен прогресс здания {building_name} для эмулятора {emulator_id}")
                    return True
                else:
                    logger.warning(f"Здание {building_name} не найдено для эмулятора {emulator_id}")
                    return False

        except Exception as e:
            logger.error(f"Ошибка обновления прогресса здания: {e}")
            return False

    def get_active_buildings(self, emulator_id: int) -> List[Dict[str, Any]]:
        """Получение списка активно строящихся зданий"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM building_progress 
                WHERE emulator_id = ? AND is_building = TRUE
                ORDER BY estimated_completion
            ''', (emulator_id,))
            return [dict(row) for row in cursor.fetchall()]

    def update_building_targets_for_lord_level(self, emulator_id: int, target_lord_level: int) -> bool:
        """
        Обновление целевых уровней зданий на основе требований лорда

        Args:
            emulator_id: ID эмулятора
            target_lord_level: Целевой уровень лорда

        Returns:
            True если обновление успешно, False иначе
        """
        try:
            # Получаем требования для целевого уровня лорда
            requirements = self.get_lord_requirements(target_lord_level)

            if 'buildings' not in requirements:
                logger.warning(f"Нет требований к зданиям для лорда {target_lord_level}")
                return True

            with self.get_connection() as conn:
                cursor = conn.cursor()

                updated_count = 0
                for building_name, required_level in requirements['buildings'].items():
                    # Обновляем целевой уровень здания
                    cursor.execute('''
                        UPDATE building_progress 
                        SET target_level = CASE 
                            WHEN target_level < ? THEN ?
                            ELSE target_level
                        END,
                        updated_at = CURRENT_TIMESTAMP
                        WHERE emulator_id = ? AND building_name = ?
                    ''', (required_level, required_level, emulator_id, building_name))

                    if cursor.rowcount > 0:
                        updated_count += 1

                conn.commit()

            logger.info(f"Обновлены цели для {updated_count} зданий (лорд {target_lord_level})")
            return True

        except Exception as e:
            logger.error(f"Ошибка обновления целей зданий: {e}")
            return False

    def update_research_targets_for_lord_level(self, emulator_id: int, target_lord_level: int) -> bool:
        """
        Обновление целевых уровней исследований на основе требований лорда

        Args:
            emulator_id: ID эмулятора
            target_lord_level: Целевой уровень лорда

        Returns:
            True если обновление успешно, False иначе
        """
        try:
            requirements = self.get_lord_requirements(target_lord_level)

            if 'research' not in requirements:
                logger.warning(f"Нет требований к исследованиям для лорда {target_lord_level}")
                return True

            with self.get_connection() as conn:
                cursor = conn.cursor()

                updated_count = 0
                for research_name, required_level in requirements['research'].items():
                    cursor.execute('''
                        UPDATE research_progress 
                        SET target_level = CASE 
                            WHEN target_level < ? THEN ?
                            ELSE target_level
                        END,
                        updated_at = CURRENT_TIMESTAMP
                        WHERE emulator_id = ? AND research_name = ?
                    ''', (required_level, required_level, emulator_id, research_name))

                    if cursor.rowcount > 0:
                        updated_count += 1

                conn.commit()

            logger.info(f"Обновлены цели для {updated_count} исследований (лорд {target_lord_level})")
            return True

        except Exception as e:
            logger.error(f"Ошибка обновления целей исследований: {e}")
            return False

    def get_building_progress_for_lord(self, emulator_id: int, target_lord_level: int) -> Dict[str, Any]:
        """
        Получение прогресса зданий для конкретного уровня лорда

        Args:
            emulator_id: ID эмулятора
            target_lord_level: Целевой уровень лорда

        Returns:
            Детальный прогресс по зданиям для лорда
        """
        requirements = self.get_lord_requirements(target_lord_level)
        building_requirements = requirements.get('buildings', {})

        if not building_requirements:
            return {}

        with self.get_connection() as conn:
            cursor = conn.cursor()

            progress = {
                'total_buildings': len(building_requirements),
                'completed_buildings': 0,
                'buildings_in_progress': 0,
                'buildings_ready': 0,
                'buildings_details': []
            }

            for building_name, required_level in building_requirements.items():
                cursor.execute('''
                    SELECT * FROM building_progress 
                    WHERE emulator_id = ? AND building_name = ?
                ''', (emulator_id, building_name))

                result = cursor.fetchone()

                if result:
                    building_data = dict(result)
                    current_level = building_data['current_level']
                    is_building = building_data['is_building']

                    # Определяем статус
                    if current_level >= required_level:
                        status = 'completed'
                        progress['completed_buildings'] += 1
                    elif is_building:
                        status = 'in_progress'
                        progress['buildings_in_progress'] += 1
                    else:
                        status = 'ready'
                        progress['buildings_ready'] += 1

                    building_data.update({
                        'required_level': required_level,
                        'status': status,
                        'levels_needed': max(0, required_level - current_level)
                    })

                    progress['buildings_details'].append(building_data)
                else:
                    # Здание не найдено в прогрессе
                    progress['buildings_details'].append({
                        'building_name': building_name,
                        'current_level': 0,
                        'required_level': required_level,
                        'status': 'not_initialized',
                        'levels_needed': required_level
                    })

            return progress

    def get_completed_buildings(self, emulator_id: int) -> List[Dict[str, Any]]:
        """Получение списка завершенных строительств (готовых к апгрейду)"""
        current_time = datetime.now().isoformat()

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM building_progress 
                WHERE emulator_id = ? 
                  AND is_building = TRUE 
                  AND estimated_completion <= ?
                ORDER BY estimated_completion
            ''', (emulator_id, current_time))
            return [dict(row) for row in cursor.fetchall()]
        """Получение списка завершенных строительств (готовых к апгрейду)"""
        current_time = datetime.now().isoformat()

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM building_progress 
                WHERE emulator_id = ? 
                  AND is_building = TRUE 
                  AND estimated_completion <= ?
                ORDER BY estimated_completion
            ''', (emulator_id, current_time))
            return [dict(row) for row in cursor.fetchall()]

    # === УПРАВЛЕНИЕ ПРОГРЕССОМ ИССЛЕДОВАНИЙ ===

    def init_research_progress(self, emulator_id: int, research_config: Dict[str, Dict]) -> None:
        """Инициализация прогресса исследований"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            for research_name, config in research_config.items():
                cursor.execute('''
                    SELECT id FROM research_progress 
                    WHERE emulator_id = ? AND research_name = ?
                ''', (emulator_id, research_name))

                if not cursor.fetchone():
                    cursor.execute('''
                        INSERT INTO research_progress 
                        (emulator_id, research_name, target_level, use_speedups)
                        VALUES (?, ?, ?, ?)
                    ''', (
                        emulator_id,
                        research_name,
                        config.get('target_level', 1),
                        config.get('use_speedups', False)
                    ))

            conn.commit()
            logger.info(f"Инициализирован прогресс исследований для эмулятора {emulator_id}")

    def get_research_progress(self, emulator_id: int, research_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """Получение прогресса исследований"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            if research_name:
                cursor.execute('''
                    SELECT * FROM research_progress 
                    WHERE emulator_id = ? AND research_name = ?
                ''', (emulator_id, research_name))
                result = cursor.fetchone()
                return [dict(result)] if result else []
            else:
                cursor.execute('''
                    SELECT * FROM research_progress 
                    WHERE emulator_id = ?
                    ORDER BY research_name
                ''', (emulator_id,))
                return [dict(row) for row in cursor.fetchall()]

    def update_research_progress(self, emulator_id: int, research_name: str, **kwargs) -> bool:
        """Обновление прогресса исследования"""
        allowed_fields = [
            'current_level', 'target_level', 'use_speedups',
            'is_researching', 'research_start_time', 'estimated_completion'
        ]

        update_data = {k: v for k, v in kwargs.items() if k in allowed_fields}

        if not update_data:
            return True

        set_parts = [f"{field} = ?" for field in update_data.keys()]
        set_parts.append("updated_at = CURRENT_TIMESTAMP")

        values = list(update_data.values()) + [emulator_id, research_name]
        query = f'''
            UPDATE research_progress 
            SET {', '.join(set_parts)} 
            WHERE emulator_id = ? AND research_name = ?
        '''

        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, values)
                conn.commit()

                return cursor.rowcount > 0

        except Exception as e:
            logger.error(f"Ошибка обновления прогресса исследования: {e}")
            return False

    def get_active_research(self, emulator_id: int) -> List[Dict[str, Any]]:
        """Получение списка активных исследований"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM research_progress 
                WHERE emulator_id = ? AND is_researching = TRUE
                ORDER BY estimated_completion
            ''', (emulator_id,))
            return [dict(row) for row in cursor.fetchall()]

    # === УПРАВЛЕНИЕ ТРЕБОВАНИЯМИ ЛОРДА ===

    def load_lord_requirements_from_config(self, config_path: str = "configs/building_chains.yaml") -> bool:
        """
        Загрузка требований для повышения лорда из YAML конфига

        Args:
            config_path: Путь к файлу конфигурации building_chains.yaml

        Returns:
            True если загрузка успешна, False иначе
        """
        try:
            config_file = Path(config_path)
            if not config_file.exists():
                logger.error(f"Файл конфигурации не найден: {config_path}")
                return False

            with open(config_file, 'r', encoding='utf-8') as f:
                config_data = yaml.safe_load(f)

            if 'lord_requirements' not in config_data:
                logger.error("Секция 'lord_requirements' не найдена в конфиге")
                return False

            # Преобразуем в формат для загрузки в БД
            requirements_data = config_data['lord_requirements']

            return self.load_lord_requirements(requirements_data)

        except Exception as e:
            logger.error(f"Ошибка загрузки конфигурации требований: {e}")
            return False

    def load_lord_requirements(self, requirements_data: Dict[int, Dict]) -> bool:
        """
        Загрузка требований для повышения лорда из конфига

        Args:
            requirements_data: Данные из building_chains.yaml

        Returns:
            True если загрузка успешна, False иначе
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # Очищаем старые данные
                cursor.execute('DELETE FROM lord_requirements')

                # Загружаем новые данные
                total_requirements = 0
                for lord_level, categories in requirements_data.items():
                    for category, buildings in categories.items():
                        for building_name, required_level in buildings.items():
                            cursor.execute('''
                                INSERT INTO lord_requirements 
                                (lord_level, building_name, required_level, category)
                                VALUES (?, ?, ?, ?)
                            ''', (int(lord_level), building_name, int(required_level), category))
                            total_requirements += 1

                conn.commit()

            logger.success(f"Загружено {total_requirements} требований для повышения лорда")
            return True

        except Exception as e:
            logger.error(f"Ошибка загрузки требований лорда: {e}")
            return False

    def get_lord_requirements(self, lord_level: int) -> Dict[str, Dict[str, int]]:
        """Получение требований для конкретного уровня лорда"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT category, building_name, required_level 
                FROM lord_requirements 
                WHERE lord_level = ?
                ORDER BY category, building_name
            ''', (lord_level,))

            requirements = {}
            for row in cursor.fetchall():
                category = row['category']
                if category not in requirements:
                    requirements[category] = {}
                requirements[category][row['building_name']] = row['required_level']

            return requirements

    def check_ready_for_lord_upgrade(self, emulator_id: int, current_lord_level: int) -> bool:
        """
        Проверка готовности к повышению лорда на следующий уровень

        Args:
            emulator_id: ID эмулятора в БД
            current_lord_level: Текущий уровень лорда

        Returns:
            True если готов к повышению, False иначе
        """
        target_level = current_lord_level + 1
        ready, _ = self.check_lord_upgrade_readiness(emulator_id, target_level)
        return ready

    def get_missing_requirements(self, emulator_id: int, target_lord_level: int) -> Dict[str, List[Dict[str, Any]]]:
        """
        Получение списка недостающих требований для повышения лорда

        Args:
            emulator_id: ID эмулятора в БД
            target_lord_level: Целевой уровень лорда

        Returns:
            Словарь {категория: [список недостающих элементов]}
        """
        requirements = self.get_lord_requirements(target_lord_level)
        missing = {}

        with self.get_connection() as conn:
            cursor = conn.cursor()

            for category, buildings in requirements.items():
                missing[category] = []

                for building_name, required_level in buildings.items():
                    # Получаем текущий уровень
                    if category == 'buildings':
                        cursor.execute('''
                            SELECT current_level FROM building_progress 
                            WHERE emulator_id = ? AND building_name = ?
                        ''', (emulator_id, building_name))
                    else:  # research
                        cursor.execute('''
                            SELECT current_level FROM research_progress 
                            WHERE emulator_id = ? AND research_name = ?
                        ''', (emulator_id, building_name))

                    result = cursor.fetchone()
                    current_level = result['current_level'] if result else 0

                    if current_level < required_level:
                        missing[category].append({
                            'name': building_name,
                            'current_level': current_level,
                            'required_level': required_level,
                            'levels_needed': required_level - current_level
                        })

        return missing

    def check_lord_upgrade_readiness(self, emulator_id: int, target_lord_level: int) -> Tuple[
        bool, Dict[str, List[str]]]:
        """
        Проверка готовности к повышению лорда

        Returns:
            Кортеж (готов, {категория: [список недостающих зданий/исследований]})
        """
        requirements = self.get_lord_requirements(target_lord_level)
        missing = {}
        all_ready = True

        with self.get_connection() as conn:
            cursor = conn.cursor()

            for category, buildings in requirements.items():
                missing[category] = []

                for building_name, required_level in buildings.items():
                    if category == 'buildings':
                        cursor.execute('''
                            SELECT current_level FROM building_progress 
                            WHERE emulator_id = ? AND building_name = ?
                        ''', (emulator_id, building_name))
                    else:  # research
                        cursor.execute('''
                            SELECT current_level FROM research_progress 
                            WHERE emulator_id = ? AND research_name = ?
                        ''', (emulator_id, building_name))

                    result = cursor.fetchone()
                    current_level = result['current_level'] if result else 0

                    if current_level < required_level:
                        missing[category].append(f"{building_name} ({current_level}/{required_level})")
                        all_ready = False

        return all_ready, missing

    def get_next_building_to_upgrade(self, emulator_id: int, current_lord_level: int) -> Optional[Dict[str, Any]]:
        """
        Определение следующего здания для апгрейда на основе требований лорда

        Args:
            emulator_id: ID эмулятора
            current_lord_level: Текущий уровень лорда

        Returns:
            Информация о следующем здании для апгрейда или None
        """
        # Получаем требования для следующего уровня лорда
        target_level = current_lord_level + 1
        missing = self.get_missing_requirements(emulator_id, target_level)

        # Приоритет: сначала здания, потом исследования
        for category in ['buildings', 'research']:
            if category in missing and missing[category]:
                # Сортируем по количеству нужных уровней (меньше = приоритетнее)
                sorted_missing = sorted(missing[category], key=lambda x: x['levels_needed'])

                next_item = sorted_missing[0]

                # Проверяем не строится ли уже это здание/исследование
                if category == 'buildings':
                    table = 'building_progress'
                    is_active_field = 'is_building'
                    name_field = 'building_name'
                else:
                    table = 'research_progress'
                    is_active_field = 'is_researching'
                    name_field = 'research_name'

                with self.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(f'''
                        SELECT {is_active_field} FROM {table}
                        WHERE emulator_id = ? AND {name_field} = ?
                    ''', (emulator_id, next_item['name']))

                    result = cursor.fetchone()
                    is_active = result[is_active_field] if result else False

                if not is_active:  # Если не строится/исследуется
                    return {
                        'type': category[:-1],  # 'building' или 'research'
                        'name': next_item['name'],
                        'current_level': next_item['current_level'],
                        'target_level': next_item['current_level'] + 1,  # Следующий уровень
                        'final_target': next_item['required_level'],
                        'lord_level': target_level
                    }

        return None

    def load_speedup_settings_from_config(self, config_path: str = "configs/building_chains.yaml") -> bool:
        """
        Загрузка настроек ускорений из конфига и применение к прогрессу

        Args:
            config_path: Путь к файлу конфигурации

        Returns:
            True если загрузка успешна, False иначе
        """
        try:
            config_file = Path(config_path)
            if not config_file.exists():
                logger.error(f"Файл конфигурации не найден: {config_path}")
                return False

            with open(config_file, 'r', encoding='utf-8') as f:
                config_data = yaml.safe_load(f)

            building_speedups = config_data.get('speedup_settings', {})
            research_speedups = config_data.get('research_speedup_settings', {})

            with self.get_connection() as conn:
                cursor = conn.cursor()

                # Обновляем настройки ускорений для зданий
                for building_name, use_speedup in building_speedups.items():
                    cursor.execute('''
                        UPDATE building_progress 
                        SET use_speedups = ? 
                        WHERE building_name = ?
                    ''', (use_speedup, building_name))

                # Обновляем настройки ускорений для исследований
                for research_name, use_speedup in research_speedups.items():
                    cursor.execute('''
                        UPDATE research_progress 
                        SET use_speedups = ? 
                        WHERE research_name = ?
                    ''', (use_speedup, research_name))

                conn.commit()

            buildings_updated = len(building_speedups)
            research_updated = len(research_speedups)
            logger.success(
                f"Обновлены настройки ускорений: {buildings_updated} зданий, {research_updated} исследований")
            return True

        except Exception as e:
            logger.error(f"Ошибка загрузки настроек ускорений: {e}")
            return False

    def get_buildings_ready_for_upgrade(self, emulator_id: int) -> List[Dict[str, Any]]:
        """
        Получение списка зданий готовых для апгрейда (не строящихся)

        Args:
            emulator_id: ID эмулятора

        Returns:
            Список зданий готовых для апгрейда
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM building_progress 
                WHERE emulator_id = ? 
                  AND is_building = FALSE 
                  AND current_level < target_level
                ORDER BY building_name
            ''', (emulator_id,))
            return [dict(row) for row in cursor.fetchall()]

    def get_research_ready_for_upgrade(self, emulator_id: int) -> List[Dict[str, Any]]:
        """
        Получение списка исследований готовых для апгрейда

        Args:
            emulator_id: ID эмулятора

        Returns:
            Список исследований готовых для апгрейда
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM research_progress 
                WHERE emulator_id = ? 
                  AND is_researching = FALSE 
                  AND current_level < target_level
                ORDER BY research_name
            ''', (emulator_id,))
            return [dict(row) for row in cursor.fetchall()]

    def update_emulator_lord_upgrade_status(self, emulator_id: int) -> bool:
        """
        Обновление статуса готовности к повышению лорда

        Args:
            emulator_id: ID эмулятора

        Returns:
            True если статус обновлен, False иначе
        """
        try:
            # Получаем текущий уровень лорда
            emulator = self.get_emulator_by_id(emulator_id)
            if not emulator:
                return False

            current_lord_level = emulator['lord_level']

            # Проверяем готовность к следующему уровню
            ready = self.check_ready_for_lord_upgrade(emulator_id, current_lord_level)

            # Обновляем статус
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE emulators 
                    SET ready_for_lord_upgrade = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (ready, emulator_id))
                conn.commit()

            logger.debug(f"Статус готовности к повышению лорда для эмулятора {emulator_id}: {ready}")
            return True

        except Exception as e:
            logger.error(f"Ошибка обновления статуса готовности лорда: {e}")
            return False

    def get_emulator_by_id(self, emulator_id: int) -> Optional[Dict[str, Any]]:
        """Получение эмулятора по ID"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM emulators WHERE id = ?', (emulator_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    # === УПРАВЛЕНИЕ СЕССИЯМИ ===

    def start_session(self, emulator_id: int) -> int:
        """Начало новой игровой сессии"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO sessions (emulator_id) VALUES (?)
            ''', (emulator_id,))
            conn.commit()
            session_id = cursor.lastrowid

        logger.debug(f"Начата сессия {session_id} для эмулятора {emulator_id}")
        return session_id

    def end_session(self, session_id: int, success: bool = True,
                    actions_completed: int = 0, buildings_started: int = 0,
                    research_started: int = 0, errors: str = None) -> bool:
        """Завершение игровой сессии"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE sessions 
                    SET end_time = CURRENT_TIMESTAMP,
                        success = ?,
                        actions_completed = ?,
                        buildings_started = ?,
                        research_started = ?,
                        errors = ?
                    WHERE id = ?
                ''', (success, actions_completed, buildings_started, research_started, errors, session_id))
                conn.commit()

            logger.debug(f"Завершена сессия {session_id} (успех: {success})")
            return True

        except Exception as e:
            logger.error(f"Ошибка завершения сессии {session_id}: {e}")
            return False

    def get_session_stats(self, emulator_id: int, hours: int = 24) -> Dict[str, Any]:
        """Получение статистики сессий за указанный период"""
        cutoff_time = (datetime.now() - timedelta(hours=hours)).isoformat()

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT 
                    COUNT(*) as total_sessions,
                    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as successful_sessions,
                    SUM(actions_completed) as total_actions,
                    SUM(buildings_started) as total_buildings,
                    SUM(research_started) as total_research,
                    AVG(CASE WHEN end_time IS NOT NULL 
                        THEN (julianday(end_time) - julianday(start_time)) * 24 * 60 
                        ELSE NULL END) as avg_duration_minutes
                FROM sessions 
                WHERE emulator_id = ? AND start_time >= ?
            ''', (emulator_id, cutoff_time))

            result = cursor.fetchone()
            return dict(result) if result else {}

    # === УТИЛИТЫ ===

    def get_database_stats(self) -> Dict[str, int]:
        """Получение общей статистики базы данных"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            stats = {}

            # Подсчитываем записи в таблицах
            tables = ['emulators', 'building_progress', 'research_progress',
                      'lord_requirements', 'prime_times', 'sessions']

            for table in tables:
                cursor.execute(f'SELECT COUNT(*) as count FROM {table}')
                stats[table] = cursor.fetchone()['count']

            return stats

    def cleanup_old_sessions(self, days: int = 30) -> int:
        """Очистка старых сессий"""
        cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM sessions WHERE start_time < ?', (cutoff_date,))
            deleted_count = cursor.rowcount
            conn.commit()

        if deleted_count > 0:
            logger.info(f"Удалено {deleted_count} старых сессий (старше {days} дней)")

        return deleted_count


# Глобальный экземпляр базы данных
database = Database()