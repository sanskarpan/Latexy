interface LoadingSpinnerProps {
    size?: 'sm' | 'md' | 'lg'
    className?: string
  }
  
  export default function LoadingSpinner({ size = 'md', className = '' }: LoadingSpinnerProps) {
    const sizeClasses = {
      sm: 'w-4 h-4 border-2',
      md: 'w-8 h-8 border-2',
      lg: 'w-12 h-12 border-3'
    }
  
    return (
      <div
        className={`animate-spin border-primary-600 border-t-transparent rounded-full ${sizeClasses[size]} ${className}`}
      />
    )
  }