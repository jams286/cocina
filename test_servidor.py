"""Pruebas del servidor de la cocina: python3 -m unittest -v (usa una BD temporal)."""
import os
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

_tmp = tempfile.TemporaryDirectory()
os.environ['COCINA_BD'] = str(Path(_tmp.name) / 'prueba.db')
import servidor as s  # noqa: E402


def compra(texto, factor=1):
    return s.comprable(s.analizar_ingrediente(texto), Fraction(factor))['cantidad']


class Ingredientes(unittest.TestCase):
    def test_comprable(self):
        casos = [('1/2 limón', 1, '1'), ('8 limones', 1, '8'), ('1/2 taza de mayonesa', 1, ''), ('4 hojas de lechuga', 1, ''),
                 ('2 dientes de ajo', 1, ''), ('Sal al gusto', 1, ''), ('500 g de carne', 1, '500 g'), ('500 g de carne', 2, '1 kg'),
                 ('1 litro de agua mineral', 2, '2 litros'), ('2 latas de atún', Fraction(1, 2), '1 lata'), ('½ kg de papas', 3, '1 1/2 kg'),
                 ('1/2 limón', 3, '2')]
        for texto, factor, esperado in casos:
            with self.subTest(texto=texto, factor=factor):
                self.assertEqual(compra(texto, factor), esperado)

    def test_escalar(self):
        casos = [('1 tomate', 2, '2 tomates'), ('1/2 limón', 4, '2 limones'), ('1/2 taza de mayonesa', 2, '1 taza de mayonesa'),
                 ('1 cucharada de mostaza', 3, '3 cucharadas de mostaza'), ('Sal al gusto', 2, 'Sal al gusto'), ('2 tazas de harina', Fraction(1, 4), '1/2 taza de harina'),
                 ('500 g de carne molida', 2, '1 kg de carne molida')]
        for texto, factor, esperado in casos:
            with self.subTest(texto=texto):
                self.assertEqual(s.escalar(s.analizar_ingrediente(texto), Fraction(factor))[0], esperado)

    def test_derivados(self):
        ings = [s.analizar_ingrediente(t) for t in ['1 cucharada de pepinillos picados', '1 cucharadita de jugo de los pepinillos',
                                                    '2 chiles chipotles en adobo', '1 cucharada del adobo de la lata', '1 cucharada de jugo de limón']]
        self.assertEqual([s.es_derivado(i, ings) for i in ings], [False, True, False, True, False])
        self.assertEqual(ings[3]['nombre'], 'Adobo de la lata')

    def test_numero_porciones(self):
        self.assertEqual([s.numero_porciones(t) for t in ['4', '8 hamburguesas', 'para 6', 'muchas', '']], [4, 8, 6, None, None])


class Api(unittest.TestCase):
    def setUp(self):
        s.BD.unlink(missing_ok=True)
        s.preparar_bd()
        self.r = s.crear_receta({'titulo': 'Dip', 'porciones': '4 personas',
                                 'ingredientes': ['1/2 taza de mayonesa', '1/2 limón', '1 cucharada del adobo de la lata'], 'pasos': []})

    def test_receta_escalada(self):
        r = s.leer_receta(s.conectar(), self.r['id'], 8)
        self.assertEqual((r['porciones_base'], r['porciones_ver']), (4, 8))
        self.assertEqual([i['texto'] for i in r['ingredientes']], ['1 taza de mayonesa', '1 limón', '2 cucharadas de adobo de la lata'])
        self.assertEqual([i['compra'] for i in r['ingredientes'][:2]], [{'nombre': 'Mayonesa', 'cantidad': ''}, {'nombre': 'Limón', 'cantidad': '1'}])
        self.assertEqual([i['derivado'] for i in r['ingredientes']], [False, False, True])
        self.assertNotIn('num', r['ingredientes'][0])

    def test_porciones_fuera_de_rango_usan_la_base(self):
        self.assertEqual(s.leer_receta(s.conectar(), self.r['id'], 500)['porciones_ver'], 4)

    def test_enviada(self):
        self.assertIsNone(self.r['enviada_en'])
        r = s.marcar_enviada(self.r['id'], {'porciones': 8})
        self.assertTrue(r['enviada_en'])
        self.assertEqual(r['enviada_porciones'], 8)
        with self.assertRaises(LookupError):
            s.marcar_enviada(999, {})


if __name__ == '__main__':
    unittest.main()
