import { computed } from 'vue'
import { type GlobalThemeOverrides } from 'naive-ui'
import { useTheme, type Theme, type ThemeMode } from './useTheme'

const inkOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: '#14d4a8',
    primaryColorHover: '#12ccb5',
    primaryColorPressed: '#0a9e8c',
    primaryColorSuppl: '#14d4a8',
    bodyColor: '#cceae3',
    cardColor: '#e2f3ee',
    modalColor: '#e2f3ee',
    popoverColor: '#e2f3ee',
    inputColor: '#c4e2d9',
    borderColor: 'rgba(0,0,0,0.08)',
    dividerColor: 'rgba(0,0,0,0.06)',
    hoverColor: 'rgba(0,0,0,0.04)',
    borderRadius: '14px',
    borderRadiusSmall: '10px',
    fontFamily: "'Noto Sans SC', 'Helvetica Neue', sans-serif",
  },
  Button: {
    colorPrimary: '#14d4a8',
    colorHoverPrimary: '#12ccb5',
    colorPressedPrimary: '#0a9e8c',
    textColorPrimary: '#fff',
    textColorHoverPrimary: '#fff',
    textColorPressedPrimary: '#fff',
  },
  Card: {
    color: '#e2f3ee',
    borderColor: 'rgba(0,0,0,0.06)',
    titleTextColor: '#1a2e28',
    textColor: '#3a6058',
  },
  Input: {
    color: '#c4e2d9',
    colorFocus: '#c4e2d9',
    border: '1px solid rgba(0,0,0,0.08)',
    borderFocus: '1px solid rgba(0,0,0,0.15)',
    textColor: '#1a2e28',
    placeholderColor: '#9ac0b4',
    caretColor: '#14d4a8',
  },
  Select: {
    peers: {
      InternalSelection: {
        color: '#c4e2d9',
        border: '1px solid rgba(0,0,0,0.08)',
        textColor: '#1a2e28',
      },
      InternalSelectMenu: {
        color: '#e2f3ee',
        optionCheckColor: '#14d4a8',
      },
    },
  },
  Tabs: {
    tabTextColor: '#6a9a8e',
    tabTextColorActive: '#14d4a8',
    tabTextColorHover: '#14d4a8',
    barColor: '#14d4a8',
  },
  Modal: {
    color: '#e2f3ee',
    boxShadow: '0 24px 48px rgba(0,0,0,0.12), 0 0 0 1px rgba(14,181,160,0.15)',
  },
  Drawer: {
    color: '#e2f3ee',
  },
  Popconfirm: {
    color: '#e2f3ee',
  },
}

const inkDarkOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: '#14d4a8',
    primaryColorHover: '#12ccb5',
    primaryColorPressed: '#0a9e8c',
    primaryColorSuppl: '#14d4a8',
    bodyColor: '#2d3936',
    cardColor: '#394744',
    modalColor: '#394744',
    popoverColor: '#394744',
    inputColor: '#323e3b',
    textColor1: '#d4ece6',
    textColor2: '#a0ccbc',
    borderColor: 'rgba(0,0,0,0.08)',
    dividerColor: 'rgba(0,0,0,0.08)',
    hoverColor: 'rgba(0,0,0,0.06)',
    borderRadius: '14px',
    borderRadiusSmall: '10px',
    fontFamily: "'Noto Sans SC', 'Helvetica Neue', sans-serif",
  },
  Button: {
    colorPrimary: '#14d4a8',
    colorHoverPrimary: '#12ccb5',
    colorPressedPrimary: '#0a9e8c',
    textColorPrimary: '#fff',
    textColorHoverPrimary: '#fff',
    textColorPressedPrimary: '#fff',
  },
  Card: {
    color: '#394744',
    borderColor: 'rgba(0,0,0,0.08)',
    titleTextColor: '#d4ece6',
    textColor: '#a0ccbc',
  },
  Input: {
    color: '#323e3b',
    colorFocus: '#323e3b',
    border: '1px solid rgba(0,0,0,0.08)',
    borderFocus: '1px solid rgba(0,0,0,0.15)',
    textColor: '#d4ece6',
    placeholderColor: '#5a9a8a',
    caretColor: '#14d4a8',
  },
  Select: {
    peers: {
      InternalSelection: {
        color: '#323e3b',
        border: '1px solid rgba(0,0,0,0.08)',
        textColor: '#d4ece6',
      },
      InternalSelectMenu: {
        color: '#394744',
        optionCheckColor: '#14d4a8',
      },
    },
  },
  Tabs: {
    tabTextColor: '#7ab8a8',
    tabTextColorActive: '#14d4a8',
    tabTextColorHover: '#14d4a8',
    barColor: '#14d4a8',
  },
  Modal: {
    color: '#394744',
    boxShadow: '0 24px 48px rgba(0,0,0,0.4), 0 0 0 1px rgba(20,212,168,0.15)',
  },
  Drawer: {
    color: '#394744',
  },
  Popconfirm: {
    color: '#394744',
  },
}

const breezeOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: '#9873f7',
    primaryColorHover: '#a988f9',
    primaryColorPressed: '#8a66f5',
    primaryColorSuppl: '#9873f7',
    bodyColor: '#ddd7f3',
    cardColor: '#ece8fa',
    modalColor: '#ece8fa',
    popoverColor: '#ece8fa',
    inputColor: '#c0b7e0',
    borderColor: 'rgba(0,0,0,0.08)',
    dividerColor: 'rgba(0,0,0,0.06)',
    hoverColor: 'rgba(0,0,0,0.04)',
    borderRadius: '14px',
    borderRadiusSmall: '10px',
    fontFamily: "'Noto Sans SC', 'Helvetica Neue', sans-serif",
  },
  Button: {
    colorPrimary: '#9873f7',
    colorHoverPrimary: '#a988f9',
    colorPressedPrimary: '#8a66f5',
    textColorPrimary: '#fff',
    textColorHoverPrimary: '#fff',
    textColorPressedPrimary: '#fff',
  },
  Card: {
    color: '#ece8fa',
    borderColor: 'rgba(0,0,0,0.06)',
    titleTextColor: '#201e30',
    textColor: '#504870',
  },
  Input: {
    color: '#c0b7e0',
    colorFocus: '#c0b7e0',
    border: '1px solid rgba(0,0,0,0.08)',
    borderFocus: '1px solid rgba(0,0,0,0.15)',
    textColor: '#201e30',
    placeholderColor: '#b0a8cc',
    caretColor: '#9873f7',
  },
  Select: {
    peers: {
      InternalSelection: {
        color: '#c0b7e0',
        border: '1px solid rgba(0,0,0,0.08)',
        textColor: '#201e30',
      },
      InternalSelectMenu: {
        color: '#ece8fa',
        optionCheckColor: '#9873f7',
      },
    },
  },
  Tabs: {
    tabTextColor: '#8078a0',
    tabTextColorActive: '#9873f7',
    tabTextColorHover: '#9873f7',
    barColor: '#9873f7',
  },
  Modal: {
    color: '#ece8fa',
    boxShadow: '0 24px 48px rgba(0,0,0,0.12), 0 0 0 1px rgba(152,115,247,0.15)',
  },
  Drawer: {
    color: '#ece8fa',
  },
  Popconfirm: {
    color: '#ece8fa',
  },
}

const breezeDarkOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: '#9873f7',
    primaryColorHover: '#a988f9',
    primaryColorPressed: '#8a66f5',
    primaryColorSuppl: '#9873f7',
    bodyColor: '#312d39',
    cardColor: '#3d3947',
    modalColor: '#3d3947',
    popoverColor: '#3d3947',
    inputColor: '#35323e',
    textColor1: '#ddd7f3',
    textColor2: '#a89cd0',
    borderColor: 'rgba(0,0,0,0.08)',
    dividerColor: 'rgba(0,0,0,0.08)',
    hoverColor: 'rgba(0,0,0,0.06)',
    borderRadius: '14px',
    borderRadiusSmall: '10px',
    fontFamily: "'Noto Sans SC', 'Helvetica Neue', sans-serif",
  },
  Button: {
    colorPrimary: '#9873f7',
    colorHoverPrimary: '#a988f9',
    colorPressedPrimary: '#8a66f5',
    textColorPrimary: '#fff',
    textColorHoverPrimary: '#fff',
    textColorPressedPrimary: '#fff',
  },
  Card: {
    color: '#3d3947',
    borderColor: 'rgba(0,0,0,0.08)',
    titleTextColor: '#ddd7f3',
    textColor: '#a89cd0',
  },
  Input: {
    color: '#35323e',
    colorFocus: '#35323e',
    border: '1px solid rgba(0,0,0,0.08)',
    borderFocus: '1px solid rgba(0,0,0,0.15)',
    textColor: '#ddd7f3',
    placeholderColor: '#504870',
    caretColor: '#9873f7',
  },
  Select: {
    peers: {
      InternalSelection: {
        color: '#35323e',
        border: '1px solid rgba(0,0,0,0.08)',
        textColor: '#ddd7f3',
      },
      InternalSelectMenu: {
        color: '#3d3947',
        optionCheckColor: '#9873f7',
      },
    },
  },
  Tabs: {
    tabTextColor: '#7068a0',
    tabTextColorActive: '#9873f7',
    tabTextColorHover: '#9873f7',
    barColor: '#9873f7',
  },
  Modal: {
    color: '#3d3947',
    boxShadow: '0 24px 48px rgba(0,0,0,0.4), 0 0 0 1px rgba(152,115,247,0.15)',
  },
  Drawer: {
    color: '#3d3947',
  },
  Popconfirm: {
    color: '#3d3947',
  },
}

const indigoOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: '#4338ca',
    primaryColorHover: '#4f46e5',
    primaryColorPressed: '#3730a3',
    primaryColorSuppl: '#4338ca',
    bodyColor: '#d5d2e8',
    cardColor: '#e5e2f2',
    modalColor: '#e5e2f2',
    popoverColor: '#e5e2f2',
    inputColor: '#b8b4d8',
    borderColor: 'rgba(0,0,0,0.08)',
    dividerColor: 'rgba(0,0,0,0.06)',
    hoverColor: 'rgba(0,0,0,0.04)',
    borderRadius: '14px',
    borderRadiusSmall: '10px',
    fontFamily: "'Noto Sans SC', 'Helvetica Neue', sans-serif",
  },
  Button: {
    colorPrimary: '#4338ca',
    colorHoverPrimary: '#4f46e5',
    colorPressedPrimary: '#3730a3',
    textColorPrimary: '#fff',
    textColorHoverPrimary: '#fff',
    textColorPressedPrimary: '#fff',
  },
  Card: {
    color: '#e5e2f2',
    borderColor: 'rgba(0,0,0,0.06)',
    titleTextColor: '#101030',
    textColor: '#404068',
  },
  Input: {
    color: '#b8b4d8',
    colorFocus: '#b8b4d8',
    border: '1px solid rgba(0,0,0,0.08)',
    borderFocus: '1px solid rgba(0,0,0,0.15)',
    textColor: '#101030',
    placeholderColor: '#a0a0c8',
    caretColor: '#4338ca',
  },
  Select: {
    peers: {
      InternalSelection: {
        color: '#b8b4d8',
        border: '1px solid rgba(0,0,0,0.08)',
        textColor: '#101030',
      },
      InternalSelectMenu: {
        color: '#e5e2f2',
        optionCheckColor: '#4338ca',
      },
    },
  },
  Tabs: {
    tabTextColor: '#7070a0',
    tabTextColorActive: '#4338ca',
    tabTextColorHover: '#4338ca',
    barColor: '#4338ca',
  },
  Modal: {
    color: '#e5e2f2',
    boxShadow: '0 24px 48px rgba(0,0,0,0.12), 0 0 0 1px rgba(67,56,202,0.15)',
  },
  Drawer: {
    color: '#e5e2f2',
  },
  Popconfirm: {
    color: '#e5e2f2',
  },
}

const indigoDarkOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: '#4338ca',
    primaryColorHover: '#4f46e5',
    primaryColorPressed: '#3730a3',
    primaryColorSuppl: '#4338ca',
    bodyColor: '#2e2d39',
    cardColor: '#3a3947',
    modalColor: '#3a3947',
    popoverColor: '#3a3947',
    inputColor: '#33323e',
    textColor1: '#d5d2e8',
    textColor2: '#9890c0',
    borderColor: 'rgba(0,0,0,0.08)',
    dividerColor: 'rgba(0,0,0,0.08)',
    hoverColor: 'rgba(0,0,0,0.06)',
    borderRadius: '14px',
    borderRadiusSmall: '10px',
    fontFamily: "'Noto Sans SC', 'Helvetica Neue', sans-serif",
  },
  Button: {
    colorPrimary: '#4338ca',
    colorHoverPrimary: '#4f46e5',
    colorPressedPrimary: '#3730a3',
    textColorPrimary: '#fff',
    textColorHoverPrimary: '#fff',
    textColorPressedPrimary: '#fff',
  },
  Card: {
    color: '#3a3947',
    borderColor: 'rgba(0,0,0,0.08)',
    titleTextColor: '#d5d2e8',
    textColor: '#9890c0',
  },
  Input: {
    color: '#33323e',
    colorFocus: '#33323e',
    border: '1px solid rgba(0,0,0,0.08)',
    borderFocus: '1px solid rgba(0,0,0,0.15)',
    textColor: '#d5d2e8',
    placeholderColor: '#403870',
    caretColor: '#4338ca',
  },
  Select: {
    peers: {
      InternalSelection: {
        color: '#33323e',
        border: '1px solid rgba(0,0,0,0.08)',
        textColor: '#d5d2e8',
      },
      InternalSelectMenu: {
        color: '#3a3947',
        optionCheckColor: '#4338ca',
      },
    },
  },
  Tabs: {
    tabTextColor: '#6058a0',
    tabTextColorActive: '#4338ca',
    tabTextColorHover: '#4338ca',
    barColor: '#4338ca',
  },
  Modal: {
    color: '#3a3947',
    boxShadow: '0 24px 48px rgba(0,0,0,0.4), 0 0 0 1px rgba(67,56,202,0.15)',
  },
  Drawer: {
    color: '#3a3947',
  },
  Popconfirm: {
    color: '#3a3947',
  },
}

const sakuraOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: '#e91e63',
    primaryColorHover: '#f06292',
    primaryColorPressed: '#c2185b',
    primaryColorSuppl: '#e91e63',
    bodyColor: '#f8e0e8',
    cardColor: '#fce8ee',
    modalColor: '#fce8ee',
    popoverColor: '#fce8ee',
    inputColor: '#e8c0cc',
    borderColor: 'rgba(0,0,0,0.08)',
    dividerColor: 'rgba(0,0,0,0.06)',
    hoverColor: 'rgba(0,0,0,0.04)',
    borderRadius: '16px',
    borderRadiusSmall: '12px',
    fontFamily: "'Noto Sans SC', 'Helvetica Neue', sans-serif",
  },
  Button: {
    colorPrimary: '#e91e63',
    colorHoverPrimary: '#f06292',
    colorPressedPrimary: '#c2185b',
    textColorPrimary: '#fff',
    textColorHoverPrimary: '#fff',
    textColorPressedPrimary: '#fff',
  },
  Card: {
    color: '#fce8ee',
    borderColor: 'rgba(0,0,0,0.06)',
    titleTextColor: '#3a1820',
    textColor: '#704050',
  },
  Input: {
    color: '#e8c0cc',
    colorFocus: '#e8c0cc',
    border: '1px solid rgba(0,0,0,0.08)',
    borderFocus: '1px solid rgba(0,0,0,0.15)',
    textColor: '#3a1820',
    placeholderColor: '#c8a8b4',
    caretColor: '#e91e63',
  },
  Select: {
    peers: {
      InternalSelection: {
        color: '#e8c0cc',
        border: '1px solid rgba(0,0,0,0.08)',
        textColor: '#3a1820',
      },
      InternalSelectMenu: {
        color: '#fce8ee',
        optionCheckColor: '#e91e63',
      },
    },
  },
  Tabs: {
    tabTextColor: '#a07888',
    tabTextColorActive: '#e91e63',
    tabTextColorHover: '#e91e63',
    barColor: '#e91e63',
  },
  Modal: {
    color: '#fce8ee',
    boxShadow: '0 24px 48px rgba(0,0,0,0.12), 0 0 0 1px rgba(233,30,99,0.15)',
  },
  Drawer: {
    color: '#fce8ee',
  },
  Popconfirm: {
    color: '#fce8ee',
  },
}

const sakuraDarkOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: '#e91e63',
    primaryColorHover: '#f06292',
    primaryColorPressed: '#c2185b',
    primaryColorSuppl: '#e91e63',
    bodyColor: '#392d31',
    cardColor: '#47393e',
    modalColor: '#47393e',
    popoverColor: '#47393e',
    inputColor: '#3e3236',
    textColor1: '#f8e0e8',
    textColor2: '#c88898',
    borderColor: 'rgba(0,0,0,0.08)',
    dividerColor: 'rgba(0,0,0,0.08)',
    hoverColor: 'rgba(0,0,0,0.06)',
    borderRadius: '16px',
    borderRadiusSmall: '12px',
    fontFamily: "'Noto Sans SC', 'Helvetica Neue', sans-serif",
  },
  Button: {
    colorPrimary: '#e91e63',
    colorHoverPrimary: '#f06292',
    colorPressedPrimary: '#c2185b',
    textColorPrimary: '#fff',
    textColorHoverPrimary: '#fff',
    textColorPressedPrimary: '#fff',
  },
  Card: {
    color: '#47393e',
    borderColor: 'rgba(0,0,0,0.08)',
    titleTextColor: '#f8e0e8',
    textColor: '#c88898',
  },
  Input: {
    color: '#3e3236',
    colorFocus: '#3e3236',
    border: '1px solid rgba(0,0,0,0.08)',
    borderFocus: '1px solid rgba(0,0,0,0.15)',
    textColor: '#f8e0e8',
    placeholderColor: '#603848',
    caretColor: '#e91e63',
  },
  Select: {
    peers: {
      InternalSelection: {
        color: '#3e3236',
        border: '1px solid rgba(0,0,0,0.08)',
        textColor: '#f8e0e8',
      },
      InternalSelectMenu: {
        color: '#47393e',
        optionCheckColor: '#e91e63',
      },
    },
  },
  Tabs: {
    tabTextColor: '#905868',
    tabTextColorActive: '#e91e63',
    tabTextColorHover: '#e91e63',
    barColor: '#e91e63',
  },
  Modal: {
    color: '#47393e',
    boxShadow: '0 24px 48px rgba(0,0,0,0.4), 0 0 0 1px rgba(233,30,99,0.15)',
  },
  Drawer: {
    color: '#47393e',
  },
  Popconfirm: {
    color: '#47393e',
  },
}

const emberOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: '#f57c00',
    primaryColorHover: '#f07e30',
    primaryColorPressed: '#d45f0e',
    primaryColorSuppl: '#f57c00',
    bodyColor: '#f8e8d4',
    cardColor: '#fceee0',
    modalColor: '#fceee0',
    popoverColor: '#fceee0',
    inputColor: '#e8ccb0',
    borderColor: 'rgba(0,0,0,0.08)',
    dividerColor: 'rgba(0,0,0,0.06)',
    hoverColor: 'rgba(0,0,0,0.04)',
    borderRadius: '14px',
    borderRadiusSmall: '10px',
    fontFamily: "'Noto Sans SC', 'Helvetica Neue', sans-serif",
  },
  Button: {
    colorPrimary: '#f57c00',
    colorHoverPrimary: '#f07e30',
    colorPressedPrimary: '#d45f0e',
    textColorPrimary: '#fff',
    textColorHoverPrimary: '#fff',
    textColorPressedPrimary: '#fff',
  },
  Card: {
    color: '#fceee0',
    borderColor: 'rgba(0,0,0,0.06)',
    titleTextColor: '#2e1a08',
    textColor: '#705030',
  },
  Input: {
    color: '#e8ccb0',
    colorFocus: '#e8ccb0',
    border: '1px solid rgba(0,0,0,0.08)',
    borderFocus: '1px solid rgba(0,0,0,0.15)',
    textColor: '#2e1a08',
    placeholderColor: '#c0a888',
    caretColor: '#f57c00',
  },
  Select: {
    peers: {
      InternalSelection: {
        color: '#e8ccb0',
        border: '1px solid rgba(0,0,0,0.08)',
        textColor: '#2e1a08',
      },
      InternalSelectMenu: {
        color: '#fceee0',
        optionCheckColor: '#f57c00',
      },
    },
  },
  Tabs: {
    tabTextColor: '#a08060',
    tabTextColorActive: '#f57c00',
    tabTextColorHover: '#f57c00',
    barColor: '#f57c00',
  },
  Modal: {
    color: '#fceee0',
    boxShadow: '0 24px 48px rgba(0,0,0,0.12), 0 0 0 1px rgba(245,124,0,0.15)',
  },
  Drawer: {
    color: '#fceee0',
  },
  Popconfirm: {
    color: '#fceee0',
  },
}

const emberDarkOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: '#f57c00',
    primaryColorHover: '#f07e30',
    primaryColorPressed: '#d45f0e',
    primaryColorSuppl: '#f57c00',
    bodyColor: '#39332d',
    cardColor: '#474039',
    modalColor: '#474039',
    popoverColor: '#474039',
    inputColor: '#3e3832',
    textColor1: '#f8e8d4',
    textColor2: '#c09868',
    borderColor: 'rgba(0,0,0,0.08)',
    dividerColor: 'rgba(0,0,0,0.08)',
    hoverColor: 'rgba(0,0,0,0.06)',
    borderRadius: '14px',
    borderRadiusSmall: '10px',
    fontFamily: "'Noto Sans SC', 'Helvetica Neue', sans-serif",
  },
  Button: {
    colorPrimary: '#f57c00',
    colorHoverPrimary: '#f07e30',
    colorPressedPrimary: '#d45f0e',
    textColorPrimary: '#fff',
    textColorHoverPrimary: '#fff',
    textColorPressedPrimary: '#fff',
  },
  Card: {
    color: '#474039',
    borderColor: 'rgba(0,0,0,0.08)',
    titleTextColor: '#f8e8d4',
    textColor: '#c09868',
  },
  Input: {
    color: '#3e3832',
    colorFocus: '#3e3832',
    border: '1px solid rgba(0,0,0,0.08)',
    borderFocus: '1px solid rgba(0,0,0,0.15)',
    textColor: '#f8e8d4',
    placeholderColor: '#604828',
    caretColor: '#f57c00',
  },
  Select: {
    peers: {
      InternalSelection: {
        color: '#3e3832',
        border: '1px solid rgba(0,0,0,0.08)',
        textColor: '#f8e8d4',
      },
      InternalSelectMenu: {
        color: '#474039',
        optionCheckColor: '#f57c00',
      },
    },
  },
  Tabs: {
    tabTextColor: '#906840',
    tabTextColorActive: '#f57c00',
    tabTextColorHover: '#f57c00',
    barColor: '#f57c00',
  },
  Modal: {
    color: '#474039',
    boxShadow: '0 24px 48px rgba(0,0,0,0.4), 0 0 0 1px rgba(245,124,0,0.15)',
  },
  Drawer: {
    color: '#474039',
  },
  Popconfirm: {
    color: '#474039',
  },
}

const sunflowerOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: '#ffb300',
    primaryColorHover: '#ffc933',
    primaryColorPressed: '#cc8f00',
    primaryColorSuppl: '#ffb300',
    bodyColor: '#f9f1d8',
    cardColor: '#fefaf0',
    modalColor: '#fefaf0',
    popoverColor: '#fefaf0',
    inputColor: '#ecdfb3',
    borderColor: 'rgba(0,0,0,0.08)',
    dividerColor: 'rgba(0,0,0,0.06)',
    hoverColor: 'rgba(0,0,0,0.04)',
    borderRadius: '14px',
    borderRadiusSmall: '10px',
    fontFamily: "'Noto Sans SC', 'Helvetica Neue', sans-serif",
  },
  Button: {
    colorPrimary: '#ffb300',
    colorHoverPrimary: '#ffc933',
    colorPressedPrimary: '#cc8f00',
    textColorPrimary: '#fff',
    textColorHoverPrimary: '#fff',
    textColorPressedPrimary: '#fff',
  },
  Card: {
    color: '#fefaf0',
    borderColor: 'rgba(0,0,0,0.06)',
    titleTextColor: '#2b2205',
    textColor: '#7a5f12',
  },
  Input: {
    color: '#ecdfb3',
    colorFocus: '#ecdfb3',
    border: '1px solid rgba(0,0,0,0.08)',
    borderFocus: '1px solid rgba(0,0,0,0.15)',
    textColor: '#2b2205',
    placeholderColor: '#cdb679',
    caretColor: '#ffb300',
  },
  Select: {
    peers: {
      InternalSelection: {
        color: '#ecdfb3',
        border: '1px solid rgba(0,0,0,0.08)',
        textColor: '#2b2205',
      },
      InternalSelectMenu: {
        color: '#fefaf0',
        optionCheckColor: '#ffb300',
      },
    },
  },
  Tabs: {
    tabTextColor: '#a3873f',
    tabTextColorActive: '#ffb300',
    tabTextColorHover: '#ffb300',
    barColor: '#ffb300',
  },
  Modal: {
    color: '#fefaf0',
    boxShadow: '0 24px 48px rgba(0,0,0,0.12), 0 0 0 1px rgba(255,179,0,0.15)',
  },
  Drawer: {
    color: '#fefaf0',
  },
  Popconfirm: {
    color: '#fefaf0',
  },
}

const sunflowerDarkOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: '#ffb300',
    primaryColorHover: '#ffc933',
    primaryColorPressed: '#cc8f00',
    primaryColorSuppl: '#ffb300',
    bodyColor: '#383425',
    cardColor: '#46402f',
    modalColor: '#46402f',
    popoverColor: '#46402f',
    inputColor: '#3e3826',
    textColor1: '#f9f1d8',
    textColor2: '#d4b568',
    borderColor: 'rgba(0,0,0,0.08)',
    dividerColor: 'rgba(0,0,0,0.08)',
    hoverColor: 'rgba(0,0,0,0.06)',
    borderRadius: '14px',
    borderRadiusSmall: '10px',
    fontFamily: "'Noto Sans SC', 'Helvetica Neue', sans-serif",
  },
  Button: {
    colorPrimary: '#ffb300',
    colorHoverPrimary: '#ffc933',
    colorPressedPrimary: '#cc8f00',
    textColorPrimary: '#fff',
    textColorHoverPrimary: '#fff',
    textColorPressedPrimary: '#fff',
  },
  Card: {
    color: '#46402f',
    borderColor: 'rgba(0,0,0,0.08)',
    titleTextColor: '#f9f1d8',
    textColor: '#d4b568',
  },
  Input: {
    color: '#3e3826',
    colorFocus: '#3e3826',
    border: '1px solid rgba(0,0,0,0.08)',
    borderFocus: '1px solid rgba(0,0,0,0.15)',
    textColor: '#f9f1d8',
    placeholderColor: '#6f5c30',
    caretColor: '#ffb300',
  },
  Select: {
    peers: {
      InternalSelection: {
        color: '#3e3826',
        border: '1px solid rgba(0,0,0,0.08)',
        textColor: '#f9f1d8',
      },
      InternalSelectMenu: {
        color: '#46402f',
        optionCheckColor: '#ffb300',
      },
    },
  },
  Tabs: {
    tabTextColor: '#a68a4a',
    tabTextColorActive: '#ffb300',
    tabTextColorHover: '#ffb300',
    barColor: '#ffb300',
  },
  Modal: {
    color: '#46402f',
    boxShadow: '0 24px 48px rgba(0,0,0,0.4), 0 0 0 1px rgba(255,179,0,0.15)',
  },
  Drawer: {
    color: '#46402f',
  },
  Popconfirm: {
    color: '#46402f',
  },
}

const oceanOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: '#2979ff',
    primaryColorHover: '#3580f0',
    primaryColorPressed: '#1560cc',
    primaryColorSuppl: '#2979ff',
    bodyColor: '#d0e0f8',
    cardColor: '#e0ecfc',
    modalColor: '#e0ecfc',
    popoverColor: '#e0ecfc',
    inputColor: '#b0c8e8',
    borderColor: 'rgba(0,0,0,0.08)',
    dividerColor: 'rgba(0,0,0,0.06)',
    hoverColor: 'rgba(0,0,0,0.04)',
    borderRadius: '14px',
    borderRadiusSmall: '10px',
    fontFamily: "'Noto Sans SC', 'Helvetica Neue', sans-serif",
  },
  Button: {
    colorPrimary: '#2979ff',
    colorHoverPrimary: '#3580f0',
    colorPressedPrimary: '#1560cc',
    textColorPrimary: '#fff',
    textColorHoverPrimary: '#fff',
    textColorPressedPrimary: '#fff',
  },
  Card: {
    color: '#e0ecfc',
    borderColor: 'rgba(0,0,0,0.06)',
    titleTextColor: '#0a1828',
    textColor: '#385068',
  },
  Input: {
    color: '#b0c8e8',
    colorFocus: '#b0c8e8',
    border: '1px solid rgba(0,0,0,0.08)',
    borderFocus: '1px solid rgba(0,0,0,0.15)',
    textColor: '#0a1828',
    placeholderColor: '#98b0c8',
    caretColor: '#2979ff',
  },
  Select: {
    peers: {
      InternalSelection: {
        color: '#b0c8e8',
        border: '1px solid rgba(0,0,0,0.08)',
        textColor: '#0a1828',
      },
      InternalSelectMenu: {
        color: '#e0ecfc',
        optionCheckColor: '#2979ff',
      },
    },
  },
  Tabs: {
    tabTextColor: '#6880a0',
    tabTextColorActive: '#2979ff',
    tabTextColorHover: '#2979ff',
    barColor: '#2979ff',
  },
  Modal: {
    color: '#e0ecfc',
    boxShadow: '0 24px 48px rgba(0,0,0,0.12), 0 0 0 1px rgba(41,121,255,0.15)',
  },
  Drawer: {
    color: '#e0ecfc',
  },
  Popconfirm: {
    color: '#e0ecfc',
  },
}

const oceanDarkOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: '#2979ff',
    primaryColorHover: '#3580f0',
    primaryColorPressed: '#1560cc',
    primaryColorSuppl: '#2979ff',
    bodyColor: '#2d3239',
    cardColor: '#393e47',
    modalColor: '#393e47',
    popoverColor: '#393e47',
    inputColor: '#32373e',
    textColor1: '#d0e0f8',
    textColor2: '#88a8d0',
    borderColor: 'rgba(0,0,0,0.08)',
    dividerColor: 'rgba(0,0,0,0.08)',
    hoverColor: 'rgba(0,0,0,0.06)',
    borderRadius: '14px',
    borderRadiusSmall: '10px',
    fontFamily: "'Noto Sans SC', 'Helvetica Neue', sans-serif",
  },
  Button: {
    colorPrimary: '#2979ff',
    colorHoverPrimary: '#3580f0',
    colorPressedPrimary: '#1560cc',
    textColorPrimary: '#fff',
    textColorHoverPrimary: '#fff',
    textColorPressedPrimary: '#fff',
  },
  Card: {
    color: '#393e47',
    borderColor: 'rgba(0,0,0,0.08)',
    titleTextColor: '#d0e0f8',
    textColor: '#88a8d0',
  },
  Input: {
    color: '#32373e',
    colorFocus: '#32373e',
    border: '1px solid rgba(0,0,0,0.08)',
    borderFocus: '1px solid rgba(0,0,0,0.15)',
    textColor: '#d0e0f8',
    placeholderColor: '#385068',
    caretColor: '#2979ff',
  },
  Select: {
    peers: {
      InternalSelection: {
        color: '#32373e',
        border: '1px solid rgba(0,0,0,0.08)',
        textColor: '#d0e0f8',
      },
      InternalSelectMenu: {
        color: '#393e47',
        optionCheckColor: '#2979ff',
      },
    },
  },
  Tabs: {
    tabTextColor: '#5878a0',
    tabTextColorActive: '#2979ff',
    tabTextColorHover: '#2979ff',
    barColor: '#2979ff',
  },
  Modal: {
    color: '#393e47',
    boxShadow: '0 24px 48px rgba(0,0,0,0.4), 0 0 0 1px rgba(41,121,255,0.15)',
  },
  Drawer: {
    color: '#393e47',
  },
  Popconfirm: {
    color: '#393e47',
  },
}

type ThemeOverridesEntry = { light: GlobalThemeOverrides; dark?: GlobalThemeOverrides }

const overridesMap: Record<Theme, ThemeOverridesEntry> = {
  ink: { light: inkOverrides, dark: inkDarkOverrides },
  breeze: { light: breezeOverrides, dark: breezeDarkOverrides },
  sakura: { light: sakuraOverrides, dark: sakuraDarkOverrides },
  ember: { light: emberOverrides, dark: emberDarkOverrides },
  sunflower: { light: sunflowerOverrides, dark: sunflowerDarkOverrides },
  ocean: { light: oceanOverrides, dark: oceanDarkOverrides },
  indigo: { light: indigoOverrides, dark: indigoDarkOverrides },
}

export function useNaiveTheme() {
  const { theme, mode } = useTheme()

  const naiveThemeOverrides = computed<GlobalThemeOverrides>(() => {
    const entry = overridesMap[theme.value]
    return (mode.value === 'dark' && entry.dark) ? entry.dark : entry.light
  })

  return { naiveThemeOverrides }
}
