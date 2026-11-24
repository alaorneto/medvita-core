# Tema Medvita

Tema da instância trazido pelo `med_patients` (`runtime.instance_themes` do manifesto), no formato do pacote de tema do Skeleton (`docs/appearance.md` e `docs/themes.md` do núcleo). Instalar a suíte não ativa o tema: o administrador da plataforma o ativa em `/platform/appearance/`, na tabela "Temas de apps".

| Arquivo | Origem |
|---|---|
| `images/logo.svg` | `medvita-design/assets/Logos/medvita-logo-horizontal.svg`, sem mudança |
| `images/logo-dark.svg` | O mesmo logo com as cores da versão negativa oficial (`medvita-simbolo-negativo.svg`): hastes `#D0D0D0` e `#9E9E9E`, sobreposição e nome `#FFFFFF` |
| `images/icon.png` | `medvita-design/assets/Favicon/icon-512.png` (512 × 512) |
| `fonts/poppins-semibold.woff2` | Poppins SemiBold, subconjunto latin do Google Fonts (cobre o português); licença SIL OFL 1.1 em `LICENSES/poppins-ofl.txt` |
| `theme.css` | `medvita-design/tokens.css` convertido para os tokens estáveis do núcleo |

A cor de marca (`tokens.brand_color`, `#1273c4`) gera no núcleo a escala e os tokens de marca, nos dois modos e com contraste AA. Por isso o `theme.css` não fixa nenhum token de marca: uma clínica com cor própria continua vencendo. O corpo usa a Inter do núcleo (os `.otf` da pasta da marca são a mesma fonte).

Contraste (#124), conferido por `med_patients/tests/test_theme.py` nos dois modos: branco sobre o botão de perigo, texto de perigo no cartão, texto secundário no fundo e texto de atenção no fundo de atenção, todos AA (4,5:1). No escuro, `--color-danger` é o vermelho de preenchimento (4,8:1 com branco) e o texto vermelho usa `--color-fg-danger`. Os rótulos de seção, de lista de dados e de tabela seguem sem caixa alta.

As cores dos tipos de atendimento (`--mv-type-blue` … `--mv-type-pink`, claro e escuro) pintam a faixa da agenda; o CSS da agenda cai na paleta do núcleo quando outro tema está ativo, e o tipo sempre vem escrito ao lado da cor.

Para conferir e para gerar o `.zip` (instâncias que preferem enviar o pacote):

```sh
python -m django appearance check-package med_patients/themes/medvita
python -m django appearance build-package med_patients/themes/medvita --output medvita-theme.zip
```

O `version` do `theme.json` acompanha o trem de versão da suíte, escrito pela automação de release como o dos manifestos.
