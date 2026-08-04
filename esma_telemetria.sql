-- phpMyAdmin SQL Dump
-- version 5.2.1
-- https://www.phpmyadmin.net/
--
-- Servidor: 127.0.0.1
-- Tiempo de generación: 28-06-2026 a las 20:25:56
-- Versión del servidor: 10.4.32-MariaDB
-- Versión de PHP: 8.2.12

SET SQL_MODE = "NO_AUTO_VALUE_ON_ZERO";
START TRANSACTION;
SET time_zone = "+00:00";


/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!40101 SET NAMES utf8mb4 */;

--
-- Base de datos: `esma_telemetria`
--

-- --------------------------------------------------------

--
-- Estructura de tabla para la tabla `documentos`
--

CREATE TABLE `documentos` (
  `id` int(11) NOT NULL,
  `tipo` varchar(40) NOT NULL DEFAULT 'otro' COMMENT 'contrato|reporte|manual|factura|foto|otro',
  `nombre` varchar(255) NOT NULL,
  `archivo` varchar(255) NOT NULL,
  `id_maquina` int(11) DEFAULT NULL,
  `id_obra` int(11) DEFAULT NULL,
  `subido_por` int(11) DEFAULT NULL,
  `id_carpeta` int(11) DEFAULT NULL,
  `subido_en` timestamp NOT NULL DEFAULT current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------------

--
-- Estructura de tabla para la tabla `doc_carpetas`
--

CREATE TABLE `doc_carpetas` (
  `id` int(11) NOT NULL,
  `nombre` varchar(150) NOT NULL,
  `padre_id` int(11) DEFAULT NULL COMMENT 'NULL = carpeta raíz',
  `id_obra` int(11) DEFAULT NULL COMMENT 'Obra a la que pertenece',
  `creado_en` timestamp NOT NULL DEFAULT current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

--
-- Volcado de datos para la tabla `doc_carpetas`
--

INSERT INTO `doc_carpetas` (`id`, `nombre`, `padre_id`, `id_obra`, `creado_en`) VALUES
(1, 'contrato', NULL, 5, '2026-06-28 17:28:49'),
(2, 'contratooooooooo', NULL, 6, '2026-06-28 17:37:17'),
(3, 'licitaciones y contratossss', NULL, 2, '2026-06-28 17:40:04');

-- --------------------------------------------------------

--
-- Estructura de tabla para la tabla `estado`
--

CREATE TABLE `estado` (
  `id` int(11) NOT NULL,
  `codigo_eco` varchar(20) NOT NULL,
  `serie` varchar(100) DEFAULT NULL,
  `nombre_equipo` text DEFAULT NULL,
  `marca` varchar(50) DEFAULT NULL,
  `modelo` varchar(150) DEFAULT NULL,
  `fecha_ultima_actualizacion` datetime DEFAULT NULL,
  `latitud` decimal(10,7) DEFAULT NULL,
  `longitud` decimal(10,7) DEFAULT NULL,
  `horas_totales_horometro` decimal(10,2) DEFAULT NULL,
  `nivel_combustible` decimal(5,2) DEFAULT NULL COMMENT '% 0-100',
  `capacidad_litros` decimal(8,2) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Estado actual de cada equipo';

--
-- Volcado de datos para la tabla `estado`
--

INSERT INTO `estado` (`id`, `codigo_eco`, `serie`, `nombre_equipo`, `marca`, `modelo`, `fecha_ultima_actualizacion`, `latitud`, `longitud`, `horas_totales_horometro`, `nivel_combustible`, `capacidad_litros`) VALUES
(1, 'EXC-001', 'VCEC350DC00271259', 'EXCAVADORA', 'VOLVO', 'EC350DL', '2026-06-28 12:15:18', 20.1240992, -99.4574620, 1509.02, 45.78, 500.00),
(2, 'EXC-008', 'VCEC350DC00271424', 'EXCAVADORA', 'VOLVO', 'EC350DL', '2026-06-28 12:14:55', 19.8760514, -98.9003593, 2372.10, 67.38, 500.00),
(3, 'EXC-009', 'VCEC350DP00281740', 'EXCAVADORA', 'VOLVO', 'EC350DL', '2026-06-28 12:14:57', 19.8763260, -98.9022186, 5865.67, 42.21, 500.00),
(4, 'CGD-001', 'VGEL110FAJ0071129', 'CARGADOR FRONTAL', 'VOLVO', 'L110F', '2026-06-28 12:15:00', 19.3453558, -98.7895781, 5789.24, 82.48, 310.00),
(5, 'TOR-005', '100197', 'TRACTOR', 'KOMATSU', 'D155AX-8', '2026-06-28 12:15:03', 20.1113197, -99.3342330, 8906.43, 54.02, 400.00),
(6, 'MTN-001', '60270', 'MOTOCONFORMADORA', 'KOMATSU', 'GD655-6', '2026-06-28 12:15:05', 19.2218376, -98.6663988, 3785.48, 47.45, 350.00),
(747, 'EXC-001', 'VCEC350DC00271259', 'EXCAVADORA', 'VOLVO', 'EC350DL', '2026-06-28 12:24:36', 20.1233440, -99.4570131, 7778.62, 58.90, 500.00),
(748, 'EXC-008', 'VCEC350DC00271424', 'EXCAVADORA', 'VOLVO', 'EC350DL', '2026-06-28 12:24:39', 19.8768753, -98.9008836, 5591.85, 54.69, 500.00),
(749, 'EXC-009', 'VCEC350DP00281740', 'EXCAVADORA', 'VOLVO', 'EC350DL', '2026-06-28 12:24:41', 19.8776371, -98.9015845, 8470.07, 33.49, 500.00),
(750, 'CGD-001', 'VGEL110FAJ0071129', 'CARGADOR FRONTAL', 'VOLVO', 'L110F', '2026-06-28 12:24:44', 19.3465223, -98.7885644, 4776.54, 56.72, 310.00),
(751, 'TOR-005', '100197', 'TRACTOR', 'KOMATSU', 'D155AX-8', '2026-06-28 12:24:46', 20.1115956, -99.3330333, 2108.33, 42.44, 400.00),
(752, 'MTN-001', '60270', 'MOTOCONFORMADORA', 'KOMATSU', 'GD655-6', '2026-06-28 12:24:49', 19.2219660, -98.6673586, 7248.01, 73.89, 350.00),
(753, 'EXC-001', 'VCEC350DC00271259', 'EXCAVADORA', 'VOLVO', 'EC350DL', '2026-06-28 12:25:01', 20.1235088, -99.4558276, 7778.86, 57.75, 500.00),
(754, 'EXC-008', 'VCEC350DC00271424', 'EXCAVADORA', 'VOLVO', 'EC350DL', '2026-06-28 12:25:04', 19.8761064, -98.9016777, 5592.12, 53.14, 500.00),
(755, 'EXC-009', 'VCEC350DP00281740', 'EXCAVADORA', 'VOLVO', 'EC350DL', '2026-06-28 12:25:07', 19.8777164, -98.9018891, 8470.19, 32.75, 500.00),
(756, 'CGD-001', 'VGEL110FAJ0071129', 'CARGADOR FRONTAL', 'VOLVO', 'L110F', '2026-06-28 12:25:09', 19.3456064, -98.7891594, 4776.72, 56.08, 310.00),
(757, 'TOR-005', '100197', 'TRACTOR', 'KOMATSU', 'D155AX-8', '2026-06-28 12:25:12', 20.1120397, -99.3331694, 2108.53, 41.60, 400.00),
(758, 'MTN-001', '60270', 'MOTOCONFORMADORA', 'KOMATSU', 'GD655-6', '2026-06-28 12:25:14', 19.2227583, -98.6663173, 7248.30, 72.48, 350.00),
(759, 'EXC-001', 'VCEC350DC00271259', 'EXCAVADORA', 'VOLVO', 'EC350DL', '2026-06-28 12:25:27', 20.1228217, -99.4561051, 7779.12, 55.76, 500.00),
(760, 'EXC-008', 'VCEC350DC00271424', 'EXCAVADORA', 'VOLVO', 'EC350DL', '2026-06-28 12:25:29', 19.8773415, -98.9006033, 5592.39, 52.52, 500.00),
(761, 'EXC-009', 'VCEC350DP00281740', 'EXCAVADORA', 'VOLVO', 'EC350DL', '2026-06-28 12:25:32', 19.8772091, -98.9027934, 8470.43, 31.22, 500.00),
(762, 'CGD-001', 'VGEL110FAJ0071129', 'CARGADOR FRONTAL', 'VOLVO', 'L110F', '2026-06-28 12:25:35', 19.3455110, -98.7881952, 4776.82, 54.87, 310.00),
(763, 'TOR-005', '100197', 'TRACTOR', 'KOMATSU', 'D155AX-8', '2026-06-28 12:25:37', 20.1119845, -99.3335611, 2108.72, 39.75, 400.00),
(764, 'MTN-001', '60270', 'MOTOCONFORMADORA', 'KOMATSU', 'GD655-6', '2026-06-28 12:25:40', 19.2226326, -98.6670009, 7248.47, 70.48, 350.00),
(765, 'EXC-001', 'VCEC350DC00271259', 'EXCAVADORA', 'VOLVO', 'EC350DL', '2026-06-28 12:25:52', 20.1235071, -99.4570150, 7779.24, 55.15, 500.00);

-- --------------------------------------------------------

--
-- Estructura de tabla para la tabla `historial_estado`
--

CREATE TABLE `historial_estado` (
  `id` bigint(20) NOT NULL,
  `codigo_eco` varchar(20) NOT NULL,
  `serie` varchar(100) DEFAULT NULL,
  `nombre_equipo` text DEFAULT NULL,
  `marca` varchar(50) DEFAULT NULL,
  `modelo` varchar(150) DEFAULT NULL,
  `fecha_hora` datetime NOT NULL,
  `latitud` decimal(10,7) DEFAULT NULL,
  `longitud` decimal(10,7) DEFAULT NULL,
  `horas_totales_horometro` decimal(10,2) DEFAULT NULL,
  `nivel_combustible` decimal(5,2) DEFAULT NULL,
  `capacidad_litros` decimal(8,2) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------------

--
-- Estructura de tabla para la tabla `horas_diarias`
--

CREATE TABLE `horas_diarias` (
  `id` bigint(20) NOT NULL,
  `codigo_eco` varchar(20) NOT NULL,
  `serie` varchar(100) DEFAULT NULL,
  `nombre_equipo` text DEFAULT NULL,
  `marca` varchar(50) DEFAULT NULL,
  `modelo` varchar(150) DEFAULT NULL,
  `fecha` date NOT NULL,
  `horas_trabajadas` decimal(8,2) DEFAULT NULL,
  `horas_motor_conectado` decimal(8,2) DEFAULT NULL,
  `horas_ralenti` decimal(8,2) DEFAULT NULL,
  `motor_desconectado` decimal(8,2) DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

--
-- Volcado de datos para la tabla `horas_diarias`
--

INSERT INTO `horas_diarias` (`id`, `codigo_eco`, `serie`, `nombre_equipo`, `marca`, `modelo`, `fecha`, `horas_trabajadas`, `horas_motor_conectado`, `horas_ralenti`, `motor_desconectado`) VALUES
(1, 'EXC-001', 'VCEC350DC00271259', 'EXCAVADORA', 'VOLVO', 'EC350DL', '2026-06-28', 1.84, 2.23, 0.39, 6.16),
(2, 'EXC-008', 'VCEC350DC00271424', 'EXCAVADORA', 'VOLVO', 'EC350DL', '2026-06-28', 1.53, 2.02, 0.49, 6.47),
(3, 'EXC-009', 'VCEC350DP00281740', 'EXCAVADORA', 'VOLVO', 'EC350DL', '2026-06-28', 1.59, 2.06, 0.47, 6.41),
(4, 'CGD-001', 'VGEL110FAJ0071129', 'CARGADOR FRONTAL', 'VOLVO', 'L110F', '2026-06-28', 1.22, 1.56, 0.34, 6.78),
(5, 'TOR-005', '100197', 'TRACTOR', 'KOMATSU', 'D155AX-8', '2026-06-28', 1.78, 2.20, 0.42, 6.22),
(6, 'MTN-001', '60270', 'MOTOCONFORMADORA', 'KOMATSU', 'GD655-6', '2026-06-28', 1.68, 2.18, 0.50, 6.32);

-- --------------------------------------------------------

--
-- Estructura de tabla para la tabla `incidentes`
--

CREATE TABLE `incidentes` (
  `id` int(11) NOT NULL,
  `folio` varchar(30) DEFAULT NULL,
  `codigo_eco` varchar(20) DEFAULT NULL,
  `id_obra` int(11) DEFAULT NULL,
  `fecha` date NOT NULL,
  `tipo` varchar(60) DEFAULT 'operativo' COMMENT 'ordeña|falla|operativo|seguridad|combustible',
  `descripcion` text DEFAULT NULL,
  `severidad` varchar(20) DEFAULT 'medio' COMMENT 'bajo|medio|alto|critico',
  `estado` varchar(20) DEFAULT 'abierto' COMMENT 'abierto|en_proceso|cerrado',
  `responsable` varchar(120) DEFAULT NULL,
  `reportado_por` int(11) DEFAULT NULL,
  `creado_en` timestamp NOT NULL DEFAULT current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------------

--
-- Estructura de tabla para la tabla `inspecciones`
--

CREATE TABLE `inspecciones` (
  `id` int(11) NOT NULL,
  `folio` varchar(30) DEFAULT NULL,
  `codigo_eco` varchar(20) DEFAULT NULL,
  `id_obra` int(11) DEFAULT NULL,
  `fecha` date NOT NULL,
  `inspector` varchar(120) DEFAULT NULL,
  `tipo` varchar(60) DEFAULT 'rutinaria' COMMENT 'rutinaria|combustible|mantenimiento|seguridad',
  `resultado` varchar(20) DEFAULT 'conforme' COMMENT 'conforme|observaciones|no_conforme',
  `severidad` varchar(20) DEFAULT 'bajo' COMMENT 'bajo|medio|alto|critico',
  `hallazgos` text DEFAULT NULL,
  `registrado_por` int(11) DEFAULT NULL,
  `creado_en` timestamp NOT NULL DEFAULT current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------------

--
-- Estructura de tabla para la tabla `maquinas`
--

CREATE TABLE `maquinas` (
  `id` int(11) NOT NULL,
  `eco` varchar(20) NOT NULL COMMENT 'Código ECO',
  `proveedor` varchar(100) DEFAULT NULL,
  `nombre_equipo` varchar(150) DEFAULT NULL,
  `marca` varchar(50) DEFAULT NULL,
  `modelo` varchar(150) DEFAULT NULL,
  `serie` varchar(100) DEFAULT NULL,
  `anio` smallint(6) DEFAULT NULL,
  `clasificacion` varchar(100) DEFAULT NULL,
  `cantidad` tinyint(4) DEFAULT 1,
  `id_obra` int(11) DEFAULT NULL COMMENT 'Obra asignada',
  `ubicacion` varchar(200) DEFAULT NULL,
  `link_ubicacion` varchar(500) DEFAULT NULL,
  `creado_en` timestamp NOT NULL DEFAULT current_timestamp(),
  `actualizado_en` timestamp NOT NULL DEFAULT current_timestamp() ON UPDATE current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Catálogo maestro de maquinaria';

--
-- Volcado de datos para la tabla `maquinas`
--

INSERT INTO `maquinas` (`id`, `eco`, `proveedor`, `nombre_equipo`, `marca`, `modelo`, `serie`, `anio`, `clasificacion`, `cantidad`, `id_obra`, `ubicacion`, `link_ubicacion`, `creado_en`, `actualizado_en`) VALUES
(1, 'BRD-001', 'ESMA', 'BARREDORA', 'SWEEPMASTER', 'SM 250', '33179', 2011, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(2, 'CM01', 'ESMA', 'CAMION MINERO', 'LGMG', 'MT50', 'LWJMT500JR0713153', 2013, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(3, 'CM02', 'ESMA', 'CAMION MINERO', 'LGMG', 'MT50', 'LWJMT500KR0713152', 2013, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(4, 'CM03', 'ESMA', 'CAMION MINERO', 'LGMG', 'MT50', 'LWJMT500SR0713150', 2013, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(5, 'CM04', 'ESMA', 'CAMION MINERO', 'LGMG', 'MT50', 'LWJMT500SR0713151', 2013, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(6, 'CM05', 'ESMA', 'CAMION MINERO', 'LGMG', 'MT50', 'LWJMT500AR0713125', 2013, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(7, 'CM06', 'ESMA', 'CAMION MINERO', 'LGMG', 'MT50', 'LWJMT500SR0713111', 2013, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(8, 'CGD-001', 'ESMA', 'CARGADOR FRONTAL', 'VOLVO', 'L110F', 'VGEL110FAJ0071129', 2010, 'Propia', 1, 4, NULL, NULL, '2026-06-26 17:30:29', '2026-06-28 17:22:18'),
(9, 'CNT-001', 'ESMA', 'COMPACTADOR NEUMATICO', 'HAMM', 'GRW280-12', 'H2290529', 2009, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(10, 'CPDR-001', 'ESMA', 'COMPACTADOR DOBLE  RODILLO LISO', 'HAMM', 'HD120WHV', 'H1840304', 2010, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(11, 'PCRB-001', 'ESMA', 'PLANTA DE CRIBADO', 'McCLOSKEY', 'S190-3DT', '82002', 2012, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(12, 'MCH-001', 'ESMA', 'MACHACADORA DE CONO', 'McCLOSKEY', 'C38', '71856', 0, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(13, 'CRB-002', 'ESMA', 'CRIBA SOBRE ORUGAS (SCALPER)', 'TEREX FINLAY', '883', 'TRX883M4PHRMC7468', 2021, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(14, 'EXC-001', 'ESMA', 'EXCAVADORA', 'VOLVO', 'EC350DL', 'VCEC350DC00271259', 2012, 'Propia', 1, 4, NULL, NULL, '2026-06-26 17:30:29', '2026-06-28 17:22:18'),
(15, 'EXC-002', 'ESMA', 'EXCAVADORA', 'VOLVO', 'EC350DL', 'VC3C350DL00271427', 2013, 'Propia', 1, 3, NULL, NULL, '2026-06-26 17:30:29', '2026-06-28 17:22:18'),
(16, 'EXC-003', 'ESMA', 'EXCAVADORA', 'VOLVO', 'EC350DL', 'VCEC350DK00271422', 2014, 'Propia', 1, 3, NULL, NULL, '2026-06-26 17:30:29', '2026-06-28 17:22:18'),
(17, 'EXC-004', 'ESMA', 'EXCAVADORA', 'VOLVO', 'EC350DL', 'VCEC350DJ00271437', 2013, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(18, 'EXC-005', 'ESMA', 'EXCAVADORA', 'VOLVO', 'EC350DL', 'VCEC350DH00271350', 2011, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(19, 'EXC-006', 'ESMA', 'EXCAVADORA', 'VOLVO', 'EC480 DL', 'VCEC48DK00284704', 2013, 'Propia', 1, 1, NULL, NULL, '2026-06-26 17:30:29', '2026-06-28 17:22:18'),
(20, 'GPA-001', 'ESMA', 'GENERADOR PLANTA ASFALTO', 'CATERPILLAR', '286-4920', '', 2014, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(21, 'GPC-001', 'ESMA', 'GENERADOR PLANTA CONCRETO', 'AKSA', 'APD 100-6', '', 0, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(22, 'MTN-001', 'ESMA', 'MOTOCONFORMADORA', 'KOMATSU', 'GD655-6', '60270', 2018, 'Propia', 1, 5, NULL, NULL, '2026-06-26 17:30:29', '2026-06-28 17:22:18'),
(23, 'PAG-001', 'ESMA', 'PIPA  DE AGUA', 'INTERNATIONAL', '', '', 0, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(24, 'TOR-001', 'ESMA', 'TRACTOR', 'KOMATSU', 'D85PX-18', '22022', 2015, 'Propia', 1, 5, NULL, NULL, '2026-06-26 17:30:29', '2026-06-28 17:22:18'),
(25, 'TOR-002', 'ESMA', 'TRACTOR', 'KOMATSU', 'D155AX-8', '100208', 2017, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(26, 'TOR-003', 'ESMA', 'TRACTOR', 'CATERPILLAR', 'D8T', 'CAT00D8TTKPZ01057', 2008, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(27, 'TOR-004', 'ESMA', 'TRACTOR', 'KOMATSU', 'D155AX-8', '100079', 2018, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(28, 'TOR-005', 'ESMA', 'TRACTOR', 'KOMATSU', 'D155AX-8', '100197', 2017, 'Propia', 1, 1, NULL, NULL, '2026-06-26 17:30:29', '2026-06-28 17:22:18'),
(29, 'IPT-001', 'ESMA', 'TRITURADOR IMPACTO', 'MOBIREX', 'MR110 EVO2', 'K0180339', 2010, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(30, 'VIC-001', 'ESMA', 'VIBROCOMPACTADOR CON PIÑA', 'HAMM', 'H20IP', 'H2330067', 2018, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(31, 'VIC-002', 'ESMA', 'VIBROCOMPACTADOR CON PIÑA', 'HAMM', 'H20IP', '0215271802M', 2018, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(32, 'PCTO-001', 'ESMA', 'PLANTA DE CONCRETO', 'ODISA', '4000-10', '5642', 2016, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(33, 'CGD-002', 'ESMA', 'CARGADOR FRONTAL', 'JOHN DEERE', '524KII', '1BZ524KALJD001586', 2020, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(34, 'CGD-003', 'ESMA', 'CARGADOR FRONTAL', 'VOLVO', 'L70E', 'L70EV61170', 2006, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(35, 'CNT-002', 'ESMA', 'COMPACTADOR NEUMATICO', 'HAMM', 'GRW 280-10', 'H2290024', 2013, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(36, 'CPT-001', 'ESMA', 'COMPACTADOR TANDEM', 'HAMM', 'HD 120', '2044810', 2020, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(37, 'EXC-007', 'ESMA', 'EXCAVADORA', 'VOLVO', 'EC350DL', 'VCEC350DJ00271423', 2023, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(38, 'EXC-008', 'ESMA', 'EXCAVADORA', 'VOLVO', 'EC350DL', 'VCEC350DC00271424', 2023, 'Propia', 1, 2, NULL, NULL, '2026-06-26 17:30:29', '2026-06-28 17:22:18'),
(39, 'EXC-009', 'ESMA', 'EXCAVADORA', 'VOLVO', 'EC350DL', 'VCEC350DP00281740', 2023, 'Propia', 1, 2, NULL, NULL, '2026-06-26 17:30:29', '2026-06-28 17:22:18'),
(40, 'EXC-010', 'ESMA', 'EXCAVADORA', 'VOLVO', 'EC350DL', 'VCEC350DC00281743', 2012, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(41, 'EXC-011', 'ESMA', 'EXCAVADORA', 'VOLVO', 'EC350DL', 'VCEC350DK00271534', 2019, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(42, 'EXC-012', 'ESMA', 'EXCAVADORA', 'VOLVO', 'EC350DL', 'VCEC350DV00281761', 2022, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(43, 'EXC-013', 'ESMA', 'EXCAVADORA', 'VOLVO', 'EC350DL', 'VCEC350DA00270342', 2016, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(44, 'GDR-001', 'ESMA', 'GENERADOR', 'CATERPILLAR', 'XQ400 456', 'GHJ00278', 2004, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(45, 'MTN-002', 'ESMA', 'MOTOCONFORMADORA', 'SDLG', 'G9220F', 'VLGG922FTN0600550', 2022, 'Propia', 1, 1, NULL, NULL, '2026-06-26 17:30:29', '2026-06-28 17:22:18'),
(46, 'MTN-003', 'ESMA', 'MOTOCONFORMADORA', 'SDLG', 'G9220F', 'VLGG922FPN0600548', 2022, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(47, 'MTN-004', 'ESMA', 'MOTOCONFORMADORA', 'CATERPILLAR', 'C6E10581', 'CAT0012MJB9F00295', 2008, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(48, 'PTL-001', 'ESMA', 'PETROLIZADORA', 'FREIGHTLINER', 'M2-35K', '3ALACYCS75DV57126', 2005, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(49, 'PAG-002', 'ESMA', 'PIPA  DE AGUA', 'INTERNATIONAL', '4300', '3HAMMAAR86L234631', 2006, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(50, 'PASF-001', 'ESMA', 'PLANTA DE ASFALTO', 'MARINI', 'MAGNUM 120', '5016011441', 2016, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(51, 'TAQASF-001', 'ESMA', 'TANQUE DE ALMACENAMIENTO DE ASFALTO (CALDERA)', 'TECNOGREEN', 'TGM', 'TGC-PRI-60-CC', 2018, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(52, 'IPT-002', 'ESMA', 'TRITURADOR IMPACTO', 'McCLOSKEY', 'I54', '80749', 2013, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(53, 'TRM-001', 'ESMA', 'TRITURADORA DE QUIJADA / MUELA', 'McCLOSKEY', 'J44', '73124', 0, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(54, 'VIC-004', 'ESMA', 'VIBROCOMPACTADOR', 'HAMM', '3411', 'H1792386', 2014, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(55, 'VIC-003', 'ESMA', 'VIBROCOMPACTADOR', 'CASE', '1107FX', 'NKJ1107FTNKT04773', 2022, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(56, 'VIC-005', 'ESMA', 'VIBROCOMPACTADOR', 'CATERPILLAR', 'CS-533E', 'CNG00162', 2008, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(57, 'VIC-006', 'ESMA', 'VIBROCOMPACTADOR DOBLE RODILLO', 'HAMM', 'HD130 HV', 'H1820163', 2014, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(58, 'EXC-014', 'ESMA', 'EXCAVADORA', 'VOLVO', 'ECE210DL', 'VCEC210DP00241198', 2024, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(59, 'EXC-015', 'ESMA', 'EXCAVADORA', 'VOLVO', 'ECE210DL', 'VCEC210DK00241199', 2024, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(60, 'EXC-016', 'ESMA', 'EXCAVADORA', 'VOLVO', 'ECE210DL', 'VCEC210DK00241204', 2024, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(61, 'MTN-005', 'ESMA', 'MOTOCONFORMADORA', 'SDLG', '8F6M1013ECR (G9220F)', 'VLGG922FKP0600635', 2023, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(62, 'VIC-007', 'ESMA', 'VIBROCOMPACTADOR DOBLE RODILLO', 'WALZENSUG', 'HAMM', 'H1792385', 2015, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(63, 'CGD-004', 'ESMA', 'CARGADOR FRONTAL', 'VOLVO', 'L60F', 'VCE0L60FTMOO74568', 2021, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(64, 'PASF-002', 'ESMA', 'PLANTA DE ASFALTO', 'MARINI', 'MAGNUM 140 MAX', '971323131016', 2016, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(65, 'VSJ-001', 'ESMA', 'PAVIMENTADORA DE ASFALTO VOGELE', 'VOGELE', 'SUPER 1800-2 SPRAY JET', '11822958', 2012, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(66, 'CPA-001', 'ESMA', 'COMPRESOR DE AIRE', 'SCHULZ', 'SOMAR SCT', '100025', 2015, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(67, 'CPA-002', 'ESMA', 'COMPRESOR DE AIRE', 'CINCINNATI', 'CSC-30', '91-2401030066', 2024, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(68, 'CRB-001', 'ESMA', 'CRIBA', 'McCLOSKEY', 'C39', '', 0, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(69, 'TAQASF-002', 'ESMA', 'TANQUE DE ASFALTO', 'TECNOGREEN', 'TGM-PMA-60', '00722014-60', 2014, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(70, 'VIC-008', 'ESMA', 'VIBROCOMPACTADOR CON PIÑA', 'HAMM', 'H20IP', 'WGH0H233AHAA00042', 2018, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29'),
(71, 'VIC-009', 'GREMIAL', 'VIBROCOMPACTADOR', 'CATERPILLAR', 'CS-533E', 'CBZE01403', 0, 'Propia', 1, NULL, NULL, NULL, '2026-06-26 17:30:29', '2026-06-26 17:30:29');

-- --------------------------------------------------------

--
-- Estructura de tabla para la tabla `obras`
--

CREATE TABLE `obras` (
  `id` int(11) NOT NULL,
  `nombre` varchar(200) NOT NULL,
  `cliente` varchar(150) DEFAULT NULL,
  `ubicacion` varchar(200) DEFAULT NULL,
  `latitud` decimal(10,7) DEFAULT NULL,
  `longitud` decimal(10,7) DEFAULT NULL,
  `fecha_inicio` date DEFAULT NULL,
  `fecha_fin` date DEFAULT NULL,
  `estado` varchar(20) NOT NULL DEFAULT 'activa' COMMENT 'activa|pausada|cerrada',
  `archivada` tinyint(1) NOT NULL DEFAULT 0 COMMENT '1 = obra movida al archivo histórico',
  `creado_en` timestamp NOT NULL DEFAULT current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

--
-- Volcado de datos para la tabla `obras`
--

INSERT INTO `obras` (`id`, `nombre`, `cliente`, `ubicacion`, `latitud`, `longitud`, `fecha_inicio`, `fecha_fin`, `estado`, `creado_en`) VALUES
(1, '06 - Trabajos de Conservación Palmillas', 'SCT', 'Palmillas, Querétaro', 20.1117000, -99.3341766, '2026-01-15', NULL, 'activa', '2026-06-28 17:22:17'),
(2, 'Bavíspe - Camino de acceso', 'CFE', 'Bavíspe, Sonora', 30.4833000, -108.9333000, '2026-02-01', NULL, 'activa', '2026-06-28 17:22:17'),
(3, 'Bermejillo - Rehabilitación', 'SICT', 'Bermejillo, Durango', 25.8833000, -103.6167000, '2026-03-10', NULL, 'activa', '2026-06-28 17:22:17'),
(4, 'Texcoco - Movimiento de tierras', 'GACM', 'Texcoco, Edo. Méx.', 19.3464409, -98.7880537, '2026-01-20', NULL, 'activa', '2026-06-28 17:22:17'),
(5, 'San Martín Puebla - Terracerías', 'Gobierno Puebla', 'San Martín Texmelucan, Puebla', 19.2227153, -98.6656099, '2026-02-15', NULL, 'activa', '2026-06-28 17:22:17'),
(6, 'Mazatlán - Vialidad costera', 'SEDATU', 'Mazatlán, Sinaloa', 23.2494000, -106.4111000, '2026-04-01', NULL, 'activa', '2026-06-28 17:22:17'),
(7, 'Palmillas IV - Ampliación', 'SCT', 'Palmillas, Querétaro', 20.1240027, -99.4563731, '2025-11-01', NULL, 'pausada', '2026-06-28 17:22:17');

-- --------------------------------------------------------

--
-- Estructura de tabla para la tabla `planta_config`
-- Parámetros de Planta de Asfalto por obra (1 fila por obra)
--

CREATE TABLE `planta_config` (
  `id` int(11) NOT NULL,
  `id_obra` int(11) NOT NULL,
  `densidad_asfalto` decimal(6,3) NOT NULL DEFAULT 0.940,
  `capacidad_camion_m3` decimal(6,2) NOT NULL DEFAULT 14.00,
  `umbral_asfalto_lt` int(11) NOT NULL DEFAULT 15000,
  `rend_ref_asfalto` decimal(6,2) NOT NULL DEFAULT 80.00,
  `rend_max_asfalto` decimal(6,2) NOT NULL DEFAULT 100.00,
  `umbral_alterno_lt` int(11) NOT NULL DEFAULT 10000,
  `umbral_emulsion_lt` int(11) NOT NULL DEFAULT 5000,
  `rend_ref_emulsion` decimal(6,3) NOT NULL DEFAULT 0.700,
  `rend_max_emulsion` decimal(6,3) NOT NULL DEFAULT 1.200,
  `factor_grava` decimal(5,3) NOT NULL DEFAULT 0.600 COMMENT 'm³ grava por m³ de mezcla',
  `factor_arena` decimal(5,3) NOT NULL DEFAULT 0.400 COMMENT 'm³ arena por m³ de mezcla',
  `umbral_grava_m3` int(11) NOT NULL DEFAULT 200,
  `umbral_arena_m3` int(11) NOT NULL DEFAULT 150,
  `tolerancia_remision_tn` decimal(5,2) NOT NULL DEFAULT 0.30,
  `tramo` varchar(150) DEFAULT NULL,
  `actualizado_en` timestamp NOT NULL DEFAULT current_timestamp() ON UPDATE current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Parámetros de Planta de Asfalto, editables por obra';

-- --------------------------------------------------------

--
-- Estructura de tabla para la tabla `planta_produccion`
-- Kardex diario de insumos (asfalto, alterno, emulsión, grava, arena)
--

CREATE TABLE `planta_produccion` (
  `id` int(11) NOT NULL,
  `id_obra` int(11) NOT NULL,
  `fecha` date NOT NULL,
  `material` varchar(30) DEFAULT NULL COMMENT 'Carpeta|Base|Micro',
  `num_camiones` int(11) DEFAULT NULL,
  `vol_m3` decimal(10,2) DEFAULT NULL,
  `asf_ini` decimal(10,2) DEFAULT NULL,
  `asf_desc` decimal(10,2) DEFAULT NULL,
  `asf_final` decimal(10,2) DEFAULT NULL,
  `alt_ini` decimal(10,2) DEFAULT NULL,
  `alt_desc` decimal(10,2) DEFAULT NULL,
  `alt_final` decimal(10,2) DEFAULT NULL,
  `emu_ini` decimal(10,2) DEFAULT NULL,
  `emu_desc` decimal(10,2) DEFAULT NULL,
  `emu_final` decimal(10,2) DEFAULT NULL,
  `grava_ini` decimal(10,2) DEFAULT NULL,
  `grava_recib` decimal(10,2) DEFAULT NULL,
  `arena_ini` decimal(10,2) DEFAULT NULL,
  `arena_recib` decimal(10,2) DEFAULT NULL,
  `validado` tinyint(1) NOT NULL DEFAULT 0,
  `creado_por` int(11) DEFAULT NULL,
  `creado_en` timestamp NOT NULL DEFAULT current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Consumo, rendimiento y stock de insumos: calculados en la app, no se guardan';

-- --------------------------------------------------------

--
-- Estructura de tabla para la tabla `planta_avance_fisico`
-- Tramos pavimentados (retroalimenta rendimiento y abundamiento)
--

CREATE TABLE `planta_avance_fisico` (
  `id` int(11) NOT NULL,
  `id_obra` int(11) NOT NULL,
  `fecha` date NOT NULL,
  `carril` varchar(30) DEFAULT NULL,
  `inicio` decimal(10,2) DEFAULT NULL COMMENT 'Cadenamiento inicial',
  `termino` decimal(10,2) DEFAULT NULL COMMENT 'Cadenamiento final',
  `ancho` decimal(6,2) DEFAULT NULL,
  `espesor` decimal(6,3) DEFAULT NULL,
  `creado_por` int(11) DEFAULT NULL,
  `creado_en` timestamp NOT NULL DEFAULT current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------------

--
-- Estructura de tabla para la tabla `planta_remisiones`
-- Suministro de asfalto/emulsión — base real para conciliar el pago al proveedor
--

CREATE TABLE `planta_remisiones` (
  `id` int(11) NOT NULL,
  `id_obra` int(11) NOT NULL,
  `producto` enum('asfalto','emulsion') NOT NULL DEFAULT 'asfalto',
  `proveedor` varchar(80) DEFAULT NULL,
  `fecha_llegada` date DEFAULT NULL,
  `fecha_salida` date DEFAULT NULL,
  `remision` varchar(40) DEFAULT NULL COMMENT 'No. remisión / factura',
  `certificado` varchar(40) DEFAULT NULL COMMENT 'Certificado de calidad',
  `placas_tracto` varchar(20) DEFAULT NULL,
  `placas_tanque` varchar(20) DEFAULT NULL,
  `peso_neto_envio` decimal(8,2) DEFAULT NULL COMMENT 'tn, según remisión del proveedor',
  `peso_bruto_recibo` decimal(8,2) DEFAULT NULL COMMENT 'tn, báscula ESMA',
  `tara_recibo` decimal(8,2) DEFAULT NULL COMMENT 'tn, báscula ESMA',
  `creado_por` int(11) DEFAULT NULL,
  `creado_en` timestamp NOT NULL DEFAULT current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='peso_neto_recibo y diferencia se calculan en la app (bruto-tara vs envio)';

-- --------------------------------------------------------

--
-- Estructura de tabla para la tabla `registro_diario`
--

CREATE TABLE `registro_diario` (
  `id` int(11) NOT NULL,
  `fecha` date NOT NULL,
  `id_obra` int(11) DEFAULT NULL,
  `autor` varchar(120) DEFAULT NULL,
  `clima` varchar(40) DEFAULT NULL,
  `equipos_activos` int(11) DEFAULT NULL,
  `notas` text DEFAULT NULL,
  `registrado_por` int(11) DEFAULT NULL,
  `creado_en` timestamp NOT NULL DEFAULT current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- --------------------------------------------------------

--
-- Estructura de tabla para la tabla `reportes_combustible`
--

CREATE TABLE `reportes_combustible` (
  `id` bigint(20) NOT NULL,
  `codigo_eco` varchar(20) NOT NULL,
  `nombre_equipo` varchar(150) DEFAULT NULL,
  `marca` varchar(50) DEFAULT NULL,
  `id_obra` int(11) DEFAULT NULL,
  `fecha` date NOT NULL,
  `semana` smallint(6) DEFAULT NULL COMMENT 'Semana operativa',
  `operador` varchar(120) DEFAULT NULL,
  `litros_cargados` decimal(8,2) DEFAULT NULL COMMENT 'Reportado/ticket (manual)',
  `litros_telemetria` decimal(8,2) DEFAULT NULL COMMENT 'Consumo medido por telemetría',
  `litros_faltantes` decimal(8,2) DEFAULT NULL COMMENT 'cargados - telemetría',
  `desviacion_pct` decimal(6,2) DEFAULT NULL,
  `semaforo` varchar(20) DEFAULT 'OK' COMMENT 'OK|Revisar|Alerta|Fraude Probable',
  `horas_maquina` decimal(8,2) DEFAULT NULL,
  `observaciones` text DEFAULT NULL,
  `justificado` tinyint(1) NOT NULL DEFAULT 0,
  `registrado_por` int(11) DEFAULT NULL,
  `creado_en` timestamp NOT NULL DEFAULT current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Auditoría de combustible: cargado vs telemetría';

-- --------------------------------------------------------

--
-- Estructura de tabla para la tabla `usuarios`
--

CREATE TABLE `usuarios` (
  `id` int(11) NOT NULL,
  `nombre` varchar(120) NOT NULL,
  `email` varchar(150) NOT NULL,
  `password` varchar(255) NOT NULL COMMENT 'SHA-256 hex',
  `rol` varchar(20) NOT NULL DEFAULT 'cliente',
  `id_obra_asignada` int(11) DEFAULT NULL COMMENT 'Obra que administra (solo roles supervisor/operador)',
  `activo` tinyint(1) NOT NULL DEFAULT 1,
  `creado_en` timestamp NOT NULL DEFAULT current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

--
-- Volcado de datos para la tabla `usuarios`
--

INSERT INTO `usuarios` (`id`, `nombre`, `email`, `password`, `rol`, `activo`, `creado_en`) VALUES
(1, 'Administrador ESMA', 'admin@grupoesma.com', '240be518fabd2724ddb6f04eeb1da5967448d7e831c08c8fa822809f74c720a9', 'admin', 1, '2026-06-28 17:22:17'),
(2, 'Pedro · Control Administrativo', 'pedro@grupoesma.com', '240be518fabd2724ddb6f04eeb1da5967448d7e831c08c8fa822809f74c720a9', 'admin', 1, '2026-06-28 17:22:17'),
(3, 'Supervisor de Obra', 'supervisor@grupoesma.com', '02423ab2e61297b8262449c93e19be42fb5bbb275860a7d93b1ebdc7b6535ed7', 'supervisor', 1, '2026-06-28 17:22:17'),
(4, 'Analista de Reportes', 'reportes@grupoesma.com', 'baa1e8c9e7a3650b5ab6b0c2b91c2f11c17ed96e67b27fb82c74d90a70a6981a', 'reportes', 1, '2026-06-28 17:22:17');

-- --------------------------------------------------------

--
-- Estructura de tabla para la tabla `utilizacion`
--

CREATE TABLE `utilizacion` (
  `id` bigint(20) NOT NULL,
  `codigo_eco` varchar(20) NOT NULL,
  `serie` varchar(100) DEFAULT NULL,
  `nombre_equipo` text DEFAULT NULL,
  `marca` varchar(50) DEFAULT NULL,
  `modelo` varchar(150) DEFAULT NULL,
  `fecha` date NOT NULL,
  `litros_hora` decimal(8,4) DEFAULT NULL,
  `litros_consumidos` decimal(8,2) DEFAULT NULL,
  `horas_maquina` decimal(8,2) DEFAULT NULL,
  `horas_ralenti` decimal(8,2) DEFAULT NULL,
  `ralenti_porcentaje` decimal(5,2) DEFAULT NULL COMMENT '% horas en ralentí'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

--
-- Volcado de datos para la tabla `utilizacion`
--

INSERT INTO `utilizacion` (`id`, `codigo_eco`, `serie`, `nombre_equipo`, `marca`, `modelo`, `fecha`, `litros_hora`, `litros_consumidos`, `horas_maquina`, `horas_ralenti`, `ralenti_porcentaje`) VALUES
(1, 'EXC-001', 'VCEC350DC00271259', 'EXCAVADORA', 'VOLVO', 'EC350DL', '2026-06-28', 8.0900, 29.94, 1.84, 0.39, 21.10),
(2, 'EXC-008', 'VCEC350DC00271424', 'EXCAVADORA', 'VOLVO', 'EC350DL', '2026-06-28', 22.0900, 25.04, 1.53, 0.49, 31.70),
(3, 'EXC-009', 'VCEC350DP00281740', 'EXCAVADORA', 'VOLVO', 'EC350DL', '2026-06-28', 9.2900, 24.11, 1.59, 0.47, 29.80),
(4, 'CGD-001', 'VGEL110FAJ0071129', 'CARGADOR FRONTAL', 'VOLVO', 'L110F', '2026-06-28', 11.6800, 19.97, 1.22, 0.34, 27.80),
(5, 'TOR-005', '100197', 'TRACTOR', 'KOMATSU', 'D155AX-8', '2026-06-28', 16.8000, 30.43, 1.78, 0.42, 23.70),
(6, 'MTN-001', '60270', 'MOTOCONFORMADORA', 'KOMATSU', 'GD655-6', '2026-06-28', 23.0100, 29.63, 1.68, 0.50, 29.60);

--
-- Índices para tablas volcadas
--

--
-- Indices de la tabla `documentos`
--
ALTER TABLE `documentos`
  ADD PRIMARY KEY (`id`),
  ADD KEY `idx_tipo` (`tipo`),
  ADD KEY `idx_maquina` (`id_maquina`),
  ADD KEY `idx_obra` (`id_obra`);

--
-- Indices de la tabla `doc_carpetas`
--
ALTER TABLE `doc_carpetas`
  ADD PRIMARY KEY (`id`),
  ADD KEY `idx_padre` (`padre_id`);

--
-- Indices de la tabla `estado`
--
ALTER TABLE `estado`
  ADD PRIMARY KEY (`id`);

--
-- Indices de la tabla `historial_estado`
--
ALTER TABLE `historial_estado`
  ADD PRIMARY KEY (`id`),
  ADD UNIQUE KEY `uq_eco_fecha` (`codigo_eco`,`fecha_hora`),
  ADD KEY `idx_eco_fecha` (`codigo_eco`,`fecha_hora`);

--
-- Indices de la tabla `horas_diarias`
--
ALTER TABLE `horas_diarias`
  ADD PRIMARY KEY (`id`),
  ADD UNIQUE KEY `uk_eco_fecha` (`codigo_eco`,`fecha`),
  ADD KEY `idx_eco` (`codigo_eco`),
  ADD KEY `idx_fecha` (`fecha`);

--
-- Indices de la tabla `incidentes`
--
ALTER TABLE `incidentes`
  ADD PRIMARY KEY (`id`),
  ADD KEY `idx_estado` (`estado`),
  ADD KEY `idx_severidad` (`severidad`),
  ADD KEY `idx_eco` (`codigo_eco`);

--
-- Indices de la tabla `inspecciones`
--
ALTER TABLE `inspecciones`
  ADD PRIMARY KEY (`id`),
  ADD KEY `idx_eco` (`codigo_eco`),
  ADD KEY `idx_obra` (`id_obra`),
  ADD KEY `idx_fecha` (`fecha`);

--
-- Indices de la tabla `maquinas`
--
ALTER TABLE `maquinas`
  ADD PRIMARY KEY (`id`),
  ADD UNIQUE KEY `uq_eco` (`eco`),
  ADD KEY `idx_obra` (`id_obra`),
  ADD KEY `idx_clasif` (`clasificacion`);

--
-- Indices de la tabla `obras`
--
ALTER TABLE `obras`
  ADD PRIMARY KEY (`id`),
  ADD KEY `idx_estado` (`estado`);

--
-- Indices de la tabla `planta_config`
--
ALTER TABLE `planta_config`
  ADD PRIMARY KEY (`id`),
  ADD UNIQUE KEY `uq_obra` (`id_obra`);

--
-- Indices de la tabla `planta_produccion`
--
ALTER TABLE `planta_produccion`
  ADD PRIMARY KEY (`id`),
  ADD KEY `idx_obra_fecha` (`id_obra`,`fecha`);

--
-- Indices de la tabla `planta_avance_fisico`
--
ALTER TABLE `planta_avance_fisico`
  ADD PRIMARY KEY (`id`),
  ADD KEY `idx_obra_fecha` (`id_obra`,`fecha`);

--
-- Indices de la tabla `planta_remisiones`
--
ALTER TABLE `planta_remisiones`
  ADD PRIMARY KEY (`id`),
  ADD KEY `idx_obra_producto` (`id_obra`,`producto`);

--
-- Indices de la tabla `registro_diario`
--
ALTER TABLE `registro_diario`
  ADD PRIMARY KEY (`id`),
  ADD KEY `idx_obra_fecha` (`id_obra`,`fecha`);

--
-- Indices de la tabla `reportes_combustible`
--
ALTER TABLE `reportes_combustible`
  ADD PRIMARY KEY (`id`),
  ADD UNIQUE KEY `uk_eco_fecha` (`codigo_eco`,`fecha`),
  ADD KEY `idx_semaforo` (`semaforo`),
  ADD KEY `idx_fecha` (`fecha`),
  ADD KEY `idx_obra` (`id_obra`);

--
-- Indices de la tabla `usuarios`
--
ALTER TABLE `usuarios`
  ADD PRIMARY KEY (`id`),
  ADD UNIQUE KEY `uq_email` (`email`);

--
-- Indices de la tabla `utilizacion`
--
ALTER TABLE `utilizacion`
  ADD PRIMARY KEY (`id`),
  ADD UNIQUE KEY `uk_eco_fecha` (`codigo_eco`,`fecha`),
  ADD KEY `idx_eco` (`codigo_eco`),
  ADD KEY `idx_fecha` (`fecha`);

--
-- AUTO_INCREMENT de las tablas volcadas
--

--
-- AUTO_INCREMENT de la tabla `documentos`
--
ALTER TABLE `documentos`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=4;

--
-- AUTO_INCREMENT de la tabla `doc_carpetas`
--
ALTER TABLE `doc_carpetas`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=4;

--
-- AUTO_INCREMENT de la tabla `estado`
--
ALTER TABLE `estado`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=766;

--
-- AUTO_INCREMENT de la tabla `historial_estado`
--
ALTER TABLE `historial_estado`
  MODIFY `id` bigint(20) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT de la tabla `horas_diarias`
--
ALTER TABLE `horas_diarias`
  MODIFY `id` bigint(20) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=57;

--
-- AUTO_INCREMENT de la tabla `incidentes`
--
ALTER TABLE `incidentes`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT de la tabla `inspecciones`
--
ALTER TABLE `inspecciones`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT de la tabla `maquinas`
--
ALTER TABLE `maquinas`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=72;

--
-- AUTO_INCREMENT de la tabla `obras`
--
ALTER TABLE `obras`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=8;

--
-- AUTO_INCREMENT de la tabla `planta_config`
--
ALTER TABLE `planta_config`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT de la tabla `planta_produccion`
--
ALTER TABLE `planta_produccion`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT de la tabla `planta_avance_fisico`
--
ALTER TABLE `planta_avance_fisico`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT de la tabla `planta_remisiones`
--
ALTER TABLE `planta_remisiones`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT de la tabla `registro_diario`
--
ALTER TABLE `registro_diario`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT de la tabla `reportes_combustible`
--
ALTER TABLE `reportes_combustible`
  MODIFY `id` bigint(20) NOT NULL AUTO_INCREMENT;

--
-- AUTO_INCREMENT de la tabla `usuarios`
--
ALTER TABLE `usuarios`
  MODIFY `id` int(11) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=5;

--
-- AUTO_INCREMENT de la tabla `utilizacion`
--
ALTER TABLE `utilizacion`
  MODIFY `id` bigint(20) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=57;
COMMIT;

/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
