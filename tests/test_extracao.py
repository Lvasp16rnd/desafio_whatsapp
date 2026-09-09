"""
Testes de unidade da lógica de extração e da máquina de estados do agente.

Não dependem de rede (n8n, Meta, Gemini). Importam as funções puras do
simulador (scripts/simular_whatsapp.py) e validam o comportamento esperado.

Rodar:
    pytest -q
"""

import importlib.util
import os
import sys

import pytest

# Carrega o simulador como módulo sem executar o main()
SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
SPEC = importlib.util.spec_from_file_location("simular_whatsapp", os.path.join(SCRIPTS_DIR, "simular_whatsapp.py"))
sim = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sim)


@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("meu e-mail é lucas@teste.com", "lucas@teste.com"),
        ("contato: joao.silva+dev@empresa.com.br, celular 11 98888-7777", "joao.silva+dev@empresa.com.br"),
        ("meu nome é Ana, sem email", ""),
        ("", ""),
    ],
)
def test_extrair_email(texto, esperado):
    assert sim._extrair_email(texto) == esperado


@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("celular é 63 98429-8509", "63 98429-8509"),
        ("meu número é (11) 98888-7777", "(11) 98888-7777"),
        ("não tenho celular", ""),
    ],
)
def test_extrair_celular(texto, esperado):
    assert sim._extrair_celular(texto) == esperado


@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("meu nome é Lucas Silva, meu e-mail é l@t.com, celular 63 98429-8509", "Lucas Silva"),
        ("sou a Maria Souza, email m@s.com", "Maria Souza"),
    ],
)
def test_extrair_nome(texto, esperado):
    email = sim._extrair_email(texto)
    celular = sim._extrair_celular(texto)
    assert sim._extrair_nome(texto, email, celular) == esperado


def test_fluxo_completo_estados():
    """Percorre a máquina de estados do início ao chamado aberto."""
    dados = {"nome": "", "email": "", "celular": "", "ocorrencia": ""}

    # SAUDACAO -> COLETA
    reply, estado, dados = sim._estado_local("SAUDACAO", "", dados)
    assert estado == "COLETA"
    assert "ÁUDIO" in reply or "digitar" in reply

    # COLETA com todos os dados -> CONFIRMACAO
    reply, estado, dados = sim._estado_local(
        "COLETA",
        "meu nome é Lucas Silva, e-mail lucas@teste.com, celular 63 98429-8509",
        dados,
    )
    assert estado == "CONFIRMACAO"
    assert dados["nome"] == "Lucas Silva"
    assert dados["email"] == "lucas@teste.com"
    assert dados["celular"] == "63 98429-8509"

    # CONFIRMACAO com "sim" -> PROBLEMA
    reply, estado, dados = sim._estado_local("CONFIRMACAO", "sim", dados)
    assert estado == "PROBLEMA"
    assert "problema" in reply.lower()

    # PROBLEMA -> CHAMADO (abre o chamado e guarda a ocorrência)
    reply, estado, dados = sim._estado_local(
        "PROBLEMA", "meu computador não liga", dados
    )
    assert estado == "CHAMADO"
    assert dados["ocorrencia"] == "meu computador não liga"
    assert "Chamado aberto" in reply


def test_confirmação_nao_limpa_dados():
    dados = {"nome": "Lucas", "email": "l@t.com", "celular": "63 98429-8509", "ocorrencia": ""}
    reply, estado, dados = sim._estado_local("CONFIRMACAO", "nao", dados)
    assert estado == "COLETA"
    assert dados["nome"] == "" and dados["email"] == "" and dados["celular"] == ""
