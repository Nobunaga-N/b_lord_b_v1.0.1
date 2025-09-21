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
        Обновленная полная инициализация прогресса эмулятора из конфига
        (ВКЛЮЧАЕТ загрузку веток исследований)
        """
        try:
            config_file = Path(config_path)
            if not config_file.exists():
                logger.error(f"Файл конфигурации не найден: {config_path}")
                return False

            # Загружаем ветки исследований из конфига
            if not self.load_research_branches_from_config(config_path):
                logger.warning("Не удалось загрузить ветки исследований, продолжаем с базовыми настройками")

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

            # Инициализируем прогресс исследований ИЗ ВЕТОК
            self.init_research_progress_from_branches(emulator_id)

            logger.success(f"Инициализирован прогресс эмулятора {emulator_id} из конфига с ветками исследований")
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

    def get_active_buildings(self, emulator_id: int) -> List[Dict]:
        """
        Получение списка активных строительств для эмулятора

        Args:
            emulator_id: ID эмулятора

        Returns:
            Список активных строительств с деталями
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT 
                    building_name,
                    current_level,
                    target_level,
                    build_start_time,
                    estimated_completion,
                    use_speedups
                FROM building_progress 
                WHERE emulator_id = ? AND is_building = TRUE
                ORDER BY estimated_completion ASC
            ''', (emulator_id,))

            results = cursor.fetchall()
            return [dict(row) for row in results]

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

    def get_available_research_for_upgrade(self, emulator_id: int) -> List[Dict[str, Any]]:
        """
        Получение списка доступных исследований для апгрейда
        (разблокированных по уровню лорда и не исследующихся сейчас)

        Args:
            emulator_id: ID эмулятора

        Returns:
            Список доступных исследований для апгрейда
        """
        # Получаем текущий уровень лорда эмулятора
        emulator = self.get_emulator_by_id(emulator_id)
        if not emulator:
            return []

        lord_level = emulator['lord_level']

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM research_progress 
                WHERE emulator_id = ? 
                  AND is_researching = FALSE 
                  AND current_level < target_level
                ORDER BY research_name
            ''', (emulator_id,))

            all_research = [dict(row) for row in cursor.fetchall()]

        # Фильтруем по разблокированным исследованиям
        available = []
        for research in all_research:
            research_name = research['research_name']
            if self.is_research_unlocked(research_name, lord_level):
                available.append(research)

        return available

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
        #Получение списка завершенных строительств (готовых к апгрейду)
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

    def get_active_research(self, emulator_id: int) -> List[Dict]:
        """
        Получение списка активных исследований для эмулятора

        Args:
            emulator_id: ID эмулятора

        Returns:
            Список активных исследований с деталями
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT 
                    research_name,
                    current_level,
                    target_level,
                    research_start_time,
                    estimated_completion,
                    use_speedups
                FROM research_progress 
                WHERE emulator_id = ? AND is_researching = TRUE
                ORDER BY estimated_completion ASC
            ''', (emulator_id,))

            results = cursor.fetchall()
            return [dict(row) for row in results]

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
        ИСПРАВЛЕННОЕ получение списка недостающих требований для повышения лорда
        ТОЛЬКО здания являются блокирующими требованиями

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

            # Проверяем ТОЛЬКО здания как блокирующие требования
            for category, buildings in requirements.items():
                if category == 'buildings':  # ТОЛЬКО здания блокируют лорда
                    missing[category] = []

                    for building_name, required_level in buildings.items():
                        # Получаем текущий уровень здания
                        cursor.execute('''
                            SELECT current_level FROM building_progress 
                            WHERE emulator_id = ? AND building_name = ?
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
        ИСПРАВЛЕННАЯ проверка готовности к повышению лорда
        ТОЛЬКО ЗДАНИЯ блокируют повышение лорда!
        Исследования показываются как информация, но НЕ блокируют

        Returns:
            Кортеж (готов, {категория: [список недостающих зданий/исследований]})
        """
        requirements = self.get_lord_requirements(target_lord_level)
        missing = {}
        lord_ready = True  # Готовность ТОЛЬКО по зданиям

        with self.get_connection() as conn:
            cursor = conn.cursor()

            for category, buildings in requirements.items():
                missing[category] = []

                for building_name, required_level in buildings.items():
                    # Проверяем только здания для блокировки лорда
                    if category == 'buildings':
                        cursor.execute('''
                            SELECT current_level FROM building_progress 
                            WHERE emulator_id = ? AND building_name = ?
                        ''', (emulator_id, building_name))

                        result = cursor.fetchone()
                        current_level = result['current_level'] if result else 0

                        if current_level < required_level:
                            missing[category].append(f"{building_name} ({current_level}/{required_level})")
                            lord_ready = False  # ТОЛЬКО здания блокируют лорда

            # Добавляем информацию об исследованиях (НЕ блокирующих)
            available_research = self.get_available_research_for_upgrade(emulator_id)
            if available_research:
                missing['research_info'] = []
                for research in available_research[:5]:  # Показываем первые 5
                    research_name = research['research_name']
                    current_level = research['current_level']
                    target_level = research['target_level']
                    missing['research_info'].append(f"{research_name} ({current_level}/{target_level})")

        return lord_ready, missing

    def get_next_building_to_upgrade(self, emulator_id: int, current_lord_level: int) -> Optional[Dict[str, Any]]:
        """
        Определение следующего действия для выполнения (здание ИЛИ исследование)

        ПРАВИЛЬНАЯ ЛОГИКА согласно txt файлам:
        - Здания И исследования качаются ОДНОВРЕМЕННО по готовности!
        - Если есть свободный слот строительства + недостающие здания → строить здание
        - Если есть свободный слот исследований + доступные исследования → исследовать
        - Приоритет отдается зданиям для лорда (они блокируют повышение)

        Args:
            emulator_id: ID эмулятора
            current_lord_level: Текущий уровень лорда

        Returns:
            Информация о следующем действии (здание ИЛИ исследование) или None
        """

        # ПРОВЕРЯЕМ ЗДАНИЯ ДЛЯ ЛОРДА (приоритет, т.к. блокируют повышение)
        target_level = current_lord_level + 1
        missing_buildings = self.get_missing_requirements(emulator_id, target_level)

        if 'buildings' in missing_buildings and missing_buildings['buildings']:
            # Проверяем есть ли свободные слоты для строительства
            active_buildings = self.get_active_buildings(emulator_id)
            max_building_slots = 1  # Обычно 1 слот строительства (можно сделать настраиваемым)

            if len(active_buildings) < max_building_slots:
                # Есть свободный слот для строительства
                sorted_missing = sorted(missing_buildings['buildings'], key=lambda x: x['levels_needed'])

                for building_item in sorted_missing:
                    # Проверяем не строится ли уже это здание
                    with self.get_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute('''
                            SELECT is_building FROM building_progress
                            WHERE emulator_id = ? AND building_name = ?
                        ''', (emulator_id, building_item['name']))

                        result = cursor.fetchone()
                        is_active = result['is_building'] if result else False

                    if not is_active:  # Если не строится
                        return {
                            'type': 'building',
                            'name': building_item['name'],
                            'current_level': building_item['current_level'],
                            'target_level': building_item['current_level'] + 1,
                            'final_target': building_item['required_level'],
                            'lord_level': target_level,
                            'priority': 'lord_building'  # Здания для лорда (приоритет)
                        }

        # ПРОВЕРЯЕМ ДОСТУПНЫЕ ИССЛЕДОВАНИЯ (параллельно с зданиями)
        available_research = self.get_available_research_for_upgrade(emulator_id)
        if available_research:
            # Проверяем есть ли свободные слоты для исследований
            active_research = self.get_active_research(emulator_id)
            max_research_slots = 1  # Обычно 1 слот исследований (можно сделать настраиваемым)

            if len(active_research) < max_research_slots:
                # Есть свободный слот для исследований
                # Берем первое доступное исследование (они отсортированы по порядку в ветках)
                research_item = available_research[0]

                return {
                    'type': 'research',
                    'name': research_item['research_name'],
                    'current_level': research_item['current_level'],
                    'target_level': research_item['current_level'] + 1,
                    'final_target': research_item['target_level'],
                    'lord_level': current_lord_level,
                    'priority': 'research_parallel'  # Исследования параллельно
                }

        # Если все слоты заняты или нет доступных действий
        return None

    def get_building_levels(self, emulator_id: int) -> Dict[str, int]:
        """
        Получение текущих уровней всех зданий для эмулятора

        Args:
            emulator_id: ID эмулятора

        Returns:
            Словарь {название_здания: текущий_уровень}
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT building_name, current_level 
                FROM building_progress 
                WHERE emulator_id = ?
            ''', (emulator_id,))

            results = cursor.fetchall()
            return {row['building_name']: row['current_level'] for row in results}

    def get_research_levels(self, emulator_id: int) -> Dict[str, int]:
        """
        Получение текущих уровней всех исследований для эмулятора

        Args:
            emulator_id: ID эмулятора

        Returns:
            Словарь {название_исследования: текущий_уровень}
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT research_name, current_level 
                FROM research_progress 
                WHERE emulator_id = ?
            ''', (emulator_id,))

            results = cursor.fetchall()
            return {row['research_name']: row['current_level'] for row in results}

    def get_speedup_setting(self, emulator_id: int, item_type: str, item_name: str,
                            default_value: bool = False) -> bool:
        """
        Получение настройки ускорения для конкретного здания или исследования

        Args:
            emulator_id: ID эмулятора
            item_type: Тип элемента ('buildings' или 'research')
            item_name: Название здания или исследования
            default_value: Значение по умолчанию

        Returns:
            True если включено ускорение, False если выключено
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()

            if item_type == 'buildings':
                cursor.execute('''
                    SELECT use_speedups 
                    FROM building_progress 
                    WHERE emulator_id = ? AND building_name = ?
                ''', (emulator_id, item_name))
            elif item_type == 'research':
                cursor.execute('''
                    SELECT use_speedups 
                    FROM research_progress 
                    WHERE emulator_id = ? AND research_name = ?
                ''', (emulator_id, item_name))
            else:
                return default_value

            result = cursor.fetchone()
            return result['use_speedups'] if result else default_value

    def start_building(self, emulator_id: int, building_name: str, completion_time: datetime) -> bool:
        """
        Начать строительство здания

        Args:
            emulator_id: ID эмулятора
            building_name: Название здания
            completion_time: Время завершения строительства

        Returns:
            True если успешно начато строительство
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # Получаем текущий уровень здания
                cursor.execute('''
                    SELECT current_level 
                    FROM building_progress 
                    WHERE emulator_id = ? AND building_name = ?
                ''', (emulator_id, building_name))

                result = cursor.fetchone()
                current_level = result['current_level'] if result else 0
                target_level = current_level + 1

                # Обновляем или создаем запись
                cursor.execute('''
                    INSERT OR REPLACE INTO building_progress (
                        emulator_id, building_name, current_level, target_level,
                        is_building, build_start_time, estimated_completion, updated_at
                    ) VALUES (?, ?, ?, ?, TRUE, ?, ?, ?)
                ''', (
                    emulator_id, building_name, current_level, target_level,
                    datetime.now(), completion_time, datetime.now()
                ))

                conn.commit()
                logger.debug(
                    f"Начато строительство {building_name} {current_level}->{target_level} для эмулятора {emulator_id}")
                return True

        except Exception as e:
            logger.error(f"Ошибка начала строительства {building_name}: {e}")
            return False

    def start_research(self, emulator_id: int, research_name: str, completion_time: datetime) -> bool:
        """
        Начать исследование

        Args:
            emulator_id: ID эмулятора
            research_name: Название исследования
            completion_time: Время завершения исследования

        Returns:
            True если успешно начато исследование
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # Получаем текущий уровень исследования
                cursor.execute('''
                    SELECT current_level 
                    FROM research_progress 
                    WHERE emulator_id = ? AND research_name = ?
                ''', (emulator_id, research_name))

                result = cursor.fetchone()
                current_level = result['current_level'] if result else 0
                target_level = current_level + 1

                # Обновляем или создаем запись
                cursor.execute('''
                    INSERT OR REPLACE INTO research_progress (
                        emulator_id, research_name, current_level, target_level,
                        is_researching, research_start_time, estimated_completion, updated_at
                    ) VALUES (?, ?, ?, ?, TRUE, ?, ?, ?)
                ''', (
                    emulator_id, research_name, current_level, target_level,
                    datetime.now(), completion_time, datetime.now()
                ))

                conn.commit()
                logger.debug(f"Начато исследование {research_name} уровень {target_level} для эмулятора {emulator_id}")
                return True

        except Exception as e:
            logger.error(f"Ошибка начала исследования {research_name}: {e}")
            return False

    def complete_building(self, emulator_id: int, building_name: str) -> bool:
        """
        Завершить строительство здания

        Args:
            emulator_id: ID эмулятора
            building_name: Название здания

        Returns:
            True если успешно завершено
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # Получаем информацию о строительстве
                cursor.execute('''
                    SELECT target_level 
                    FROM building_progress 
                    WHERE emulator_id = ? AND building_name = ? AND is_building = TRUE
                ''', (emulator_id, building_name))

                result = cursor.fetchone()
                if not result:
                    logger.warning(f"Нет активного строительства {building_name} для эмулятора {emulator_id}")
                    return False

                target_level = result['target_level']

                # Завершаем строительство
                cursor.execute('''
                    UPDATE building_progress 
                    SET current_level = target_level,
                        is_building = FALSE,
                        build_start_time = NULL,
                        estimated_completion = NULL,
                        updated_at = ?
                    WHERE emulator_id = ? AND building_name = ?
                ''', (datetime.now(), emulator_id, building_name))

                conn.commit()
                logger.info(
                    f"Завершено строительство {building_name} уровень {target_level} для эмулятора {emulator_id}")
                return True

        except Exception as e:
            logger.error(f"Ошибка завершения строительства {building_name}: {e}")
            return False

    def complete_research(self, emulator_id: int, research_name: str) -> bool:
        """
        Завершить исследование

        Args:
            emulator_id: ID эмулятора
            research_name: Название исследования

        Returns:
            True если успешно завершено
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # Получаем информацию об исследовании
                cursor.execute('''
                    SELECT target_level 
                    FROM research_progress 
                    WHERE emulator_id = ? AND research_name = ? AND is_researching = TRUE
                ''', (emulator_id, research_name))

                result = cursor.fetchone()
                if not result:
                    logger.warning(f"Нет активного исследования {research_name} для эмулятора {emulator_id}")
                    return False

                target_level = result['target_level']

                # Завершаем исследование
                cursor.execute('''
                    UPDATE research_progress 
                    SET current_level = target_level,
                        is_researching = FALSE,
                        research_start_time = NULL,
                        estimated_completion = NULL,
                        updated_at = ?
                    WHERE emulator_id = ? AND research_name = ?
                ''', (datetime.now(), emulator_id, research_name))

                conn.commit()
                logger.info(
                    f"Завершено исследование {research_name} уровень {target_level} для эмулятора {emulator_id}")
                return True

        except Exception as e:
            logger.error(f"Ошибка завершения исследования {research_name}: {e}")
            return False

    def set_building_speedup(self, emulator_id: int, building_name: str, use_speedup: bool) -> bool:
        """
        Установить настройку ускорения для здания

        Args:
            emulator_id: ID эмулятора
            building_name: Название здания
            use_speedup: Включить/выключить ускорение

        Returns:
            True если успешно установлено
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # Обновляем или создаем запись
                cursor.execute('''
                    INSERT OR REPLACE INTO building_progress (
                        emulator_id, building_name, current_level, target_level,
                        use_speedups, updated_at
                    ) VALUES (?, ?, COALESCE((
                        SELECT current_level FROM building_progress 
                        WHERE emulator_id = ? AND building_name = ?
                    ), 0), COALESCE((
                        SELECT target_level FROM building_progress 
                        WHERE emulator_id = ? AND building_name = ?
                    ), 0), ?, ?)
                ''', (
                    emulator_id, building_name, emulator_id, building_name,
                    emulator_id, building_name, use_speedup, datetime.now()
                ))

                conn.commit()
                logger.debug(f"Установлено ускорение {building_name}: {use_speedup} для эмулятора {emulator_id}")
                return True

        except Exception as e:
            logger.error(f"Ошибка установки ускорения {building_name}: {e}")
            return False

    def set_research_speedup(self, emulator_id: int, research_name: str, use_speedup: bool) -> bool:
        """
        Установить настройку ускорения для исследования

        Args:
            emulator_id: ID эмулятора
            research_name: Название исследования
            use_speedup: Включить/выключить ускорение

        Returns:
            True если успешно установлено
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # Обновляем или создаем запись
                cursor.execute('''
                    INSERT OR REPLACE INTO research_progress (
                        emulator_id, research_name, current_level, target_level,
                        use_speedups, updated_at
                    ) VALUES (?, ?, COALESCE((
                        SELECT current_level FROM research_progress 
                        WHERE emulator_id = ? AND research_name = ?
                    ), 0), COALESCE((
                        SELECT target_level FROM research_progress 
                        WHERE emulator_id = ? AND research_name = ?
                    ), 0), ?, ?)
                ''', (
                    emulator_id, research_name, emulator_id, research_name,
                    emulator_id, research_name, use_speedup, datetime.now()
                ))

                conn.commit()
                logger.debug(f"Установлено ускорение {research_name}: {use_speedup} для эмулятора {emulator_id}")
                return True

        except Exception as e:
            logger.error(f"Ошибка установки ускорения {research_name}: {e}")
            return False

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

    def load_research_branches_from_config(self, config_path: str = "configs/building_chains.yaml") -> bool:
        """
        Загрузка веток исследований из конфига

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

            if 'research_branches' not in config_data:
                logger.warning("Секция 'research_branches' не найдена в конфиге, используем встроенные ограничения")
                return True

            # Сохраняем ветки исследований в атрибуте класса для быстрого доступа
            self._research_branches = config_data['research_branches']

            logger.success(f"Загружены ветки исследований: {list(self._research_branches.keys())}")
            return True

        except Exception as e:
            logger.error(f"Ошибка загрузки веток исследований: {e}")
            return False

    def get_research_branches_restrictions(self) -> Dict[str, Dict[str, Any]]:
        """
        Получение ограничений веток исследований по уровню лорда
        (из конфига или встроенных)

        Returns:
            Словарь {ветка: {min_lord_level: int, researches: dict}}
        """
        # Если загружены из конфига, используем их
        if hasattr(self, '_research_branches') and self._research_branches:
            return self._research_branches

        # Иначе используем встроенные ограничения как fallback (по txt файлам)
        logger.warning("Используем встроенные ограничения веток исследований")
        return {
            'territory_development': {
                'min_lord_level': 10,
                'researches': {
                    'развитие_территории': 1, 'изобилие_света': 5, 'сапротрофное_удобрение': 5,
                    'выхлый_грунт': 5, 'плодородная_почва': 5, 'журчащий_источник': 5,
                    'массивный_песчаник': 5, 'гигантский_улей': 10, 'загруженный_сборщик': 5,
                    'резвый_подъем': 10, 'мягкая_почва': 10, 'скоростная_перевозка': 10,
                    'меткая_резка': 1, 'накопитель': 10
                }
            },
            'basic_combat': {
                'min_lord_level': 13,
                'researches': {
                    'похвала_за_смелость': 1, 'мутация_травоядных_1': 1, 'мутация_плотоядных_1': 1,
                    'мутация_всеядных_1': 1, 'сверх_грабеж': 5, 'начальная_атака': 3, 'начальная_защита': 3,
                    'мутация_травоядных_2': 1, 'мутация_плотоядных_2': 1, 'мутация_всеядных_2': 1,
                    'увеличение_опыта': 3, 'средняя_атака': 2, 'средняя_защита': 2, 'навык_уклонения': 5,
                    'продвинутая_атака': 5, 'продвинутая_защита': 3
                }
            },
            'medium_combat': {
                'min_lord_level': 14,
                'researches': {
                    'преимущество_скорости': 5, 'особый_отряд': 1, 'эффективный_сбор': 5,
                    'увеличение_грузоподъемности': 5
                }
            },
            'march_squads': {
                'min_lord_level': 17,
                'researches': {
                    'походный_отряд_1': 1, 'походный_отряд_2': 1, 'походный_отряд_3': 1,
                    'развитие_района': 1, 'доп_награды': 10, 'средние_награды': 1,
                    'эволюция_плотоядных': 1, 'клыки_и_когти_1': 5
                }
            }
        }

    def is_research_unlocked(self, research_name: str, lord_level: int) -> bool:
        """
        Проверка разблокировано ли исследование для текущего уровня лорда

        Args:
            research_name: Название исследования
            lord_level: Текущий уровень лорда

        Returns:
            True если исследование разблокировано, False иначе
        """
        branches = self.get_research_branches_restrictions()

        for branch_name, branch_data in branches.items():
            researches = branch_data.get('researches', {})
            if research_name in researches:
                min_level = branch_data.get('min_lord_level', 10)
                is_unlocked = lord_level >= min_level

                if not is_unlocked:
                    logger.debug(f"Исследование '{research_name}' заблокировано для лорда {lord_level} "
                                 f"(требуется минимум {min_level}, ветка: {branch_name})")

                return is_unlocked

        # Если исследование не найдено в ветках, считаем его разблокированным
        logger.warning(f"Исследование '{research_name}' не найдено в ветках ограничений")
        return True

    def get_research_max_level(self, research_name: str) -> int:
        """
        Получение максимального уровня исследования из конфига

        Args:
            research_name: Название исследования

        Returns:
            Максимальный уровень исследования
        """
        branches = self.get_research_branches_restrictions()

        for branch_name, branch_data in branches.items():
            researches = branch_data.get('researches', {})
            if research_name in researches:
                return researches[research_name]

        # Если не найдено, возвращаем 1 как базовый уровень
        logger.warning(f"Максимальный уровень для исследования '{research_name}' не найден, используем 1")
        return 1

    def init_research_progress_from_branches(self, emulator_id: int) -> bool:
        """
        Инициализация прогресса исследований на основе веток из конфига

        Args:
            emulator_id: ID эмулятора

        Returns:
            True если инициализация успешна, False иначе
        """
        try:
            branches = self.get_research_branches_restrictions()

            # Получаем настройки ускорений из конфига
            config_file = Path("configs/building_chains.yaml")
            research_speedups = {}

            if config_file.exists():
                with open(config_file, 'r', encoding='utf-8') as f:
                    config_data = yaml.safe_load(f)
                    research_speedups = config_data.get('research_speedup_settings', {})

            with self.get_connection() as conn:
                cursor = conn.cursor()

                total_researches = 0
                for branch_name, branch_data in branches.items():
                    researches = branch_data.get('researches', {})

                    for research_name, max_level in researches.items():
                        # Проверяем существует ли запись
                        cursor.execute('''
                            SELECT id FROM research_progress 
                            WHERE emulator_id = ? AND research_name = ?
                        ''', (emulator_id, research_name))

                        if not cursor.fetchone():
                            # Создаем новую запись
                            use_speedup = research_speedups.get(research_name, False)

                            cursor.execute('''
                                INSERT INTO research_progress 
                                (emulator_id, research_name, target_level, use_speedups)
                                VALUES (?, ?, ?, ?)
                            ''', (emulator_id, research_name, max_level, use_speedup))

                            total_researches += 1

                conn.commit()

            logger.success(f"Инициализировано {total_researches} исследований из веток для эмулятора {emulator_id}")
            return True

        except Exception as e:
            logger.error(f"Ошибка инициализации исследований из веток: {e}")
            return False

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