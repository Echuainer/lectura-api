-- Minimal copy of the api-colegio-smart tables that lectura-api reads (only for tests against Postgres).
CREATE TABLE institutions (id BIGSERIAL PRIMARY KEY);
CREATE TABLE users (id BIGSERIAL PRIMARY KEY, institution_id BIGINT REFERENCES institutions(id),
                    password_changed_at TIMESTAMPTZ);
CREATE TABLE cycles_types_levels (id BIGSERIAL PRIMARY KEY, name TEXT);
CREATE TABLE courses (id BIGSERIAL PRIMARY KEY, institution_id BIGINT REFERENCES institutions(id),
                      cycle_type_level_id BIGINT REFERENCES cycles_types_levels(id), letter TEXT);
CREATE TABLE students (id BIGSERIAL PRIMARY KEY, institution_id BIGINT REFERENCES institutions(id),
                       course_id BIGINT REFERENCES courses(id), name TEXT, last_name TEXT);
